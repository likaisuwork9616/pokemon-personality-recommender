"""Transactional persistence operations for the administrator interface."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    Pokemon,
    PokemonDescription,
    PokemonImage,
    PokemonKnowledgeChunk,
    PokemonKnowledgeDocument,
    PokemonStats,
    PokemonType,
    Type,
)
from app.schemas.admin import AdminPokemonCreate, AdminPokemonUpdate
from app.services.knowledge import content_hash


CORE_FIELDS = (
    "pokedex_number",
    "form_key",
    "name_zh",
    "name_en",
    "category_zh",
    "genus",
    "generation",
    "habitat",
    "color",
    "shape",
    "growth_rate",
    "abilities",
    "hidden_ability",
    "egg_groups",
    "height_m",
    "weight_kg",
    "capture_rate",
    "is_legendary",
    "is_mythical",
    "is_baby",
    "is_outlier",
    "lof_outlier",
)


class AdminPokemonRepository:
    """Manage active and inactive Pokémon inside a caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(
        self,
        *,
        q: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Pokemon], int]:
        filters = []
        normalized = (q or "").strip()
        if normalized:
            escaped = (
                normalized.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            filters.append(
                or_(
                    Pokemon.name_zh.ilike(pattern, escape="\\"),
                    Pokemon.name_en.ilike(pattern, escape="\\"),
                )
            )
        total = int(
            self.session.scalar(select(func.count(Pokemon.id)).where(*filters)) or 0
        )
        statement = (
            select(Pokemon)
            .where(*filters)
            .order_by(Pokemon.pokedex_number, Pokemon.form_key, Pokemon.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.session.scalars(statement)), total

    def get(self, pokemon_id: int) -> Pokemon | None:
        statement = (
            select(Pokemon)
            .where(Pokemon.id == pokemon_id)
            .options(
                selectinload(Pokemon.type_links).selectinload(PokemonType.type_record),
                selectinload(Pokemon.stats),
                selectinload(Pokemon.descriptions),
                selectinload(Pokemon.images),
            )
        )
        return self.session.scalar(statement)

    def create(self, payload: AdminPokemonCreate) -> Pokemon:
        values = self._core_values(payload)
        pokemon = Pokemon(**values, is_active=True)
        self.session.add(pokemon)
        self.session.flush()
        self._sync_types(pokemon, payload.type_codes)
        self._sync_stats(pokemon, payload.stats)
        self._sync_descriptions(pokemon, payload.descriptions)
        self._sync_images(pokemon, payload.images)
        self.session.flush()
        self.session.expire(pokemon)
        loaded = self.get(pokemon.id)
        if loaded is None:
            raise RuntimeError("created Pokémon could not be reloaded")
        return loaded

    def update(self, pokemon: Pokemon, payload: AdminPokemonUpdate) -> Pokemon:
        for field in CORE_FIELDS:
            if field in payload.model_fields_set:
                value = getattr(payload, field)
                if field in {"height_m", "weight_kg"} and value is not None:
                    value = Decimal(str(value))
                setattr(pokemon, field, value)
        if "type_codes" in payload.model_fields_set:
            assert payload.type_codes is not None
            self._sync_types(pokemon, payload.type_codes)
        if "stats" in payload.model_fields_set:
            self._sync_stats(pokemon, payload.stats)
        if "descriptions" in payload.model_fields_set:
            self._sync_descriptions(pokemon, payload.descriptions or [])
        if "images" in payload.model_fields_set:
            self._sync_images(pokemon, payload.images or [])
        self.session.flush()
        self.session.expire(pokemon)
        loaded = self.get(pokemon.id)
        if loaded is None:
            raise RuntimeError("updated Pokémon could not be reloaded")
        return loaded

    def set_active(self, pokemon: Pokemon, active: bool) -> Pokemon:
        pokemon.is_active = active
        self.session.flush()
        return pokemon

    @staticmethod
    def _core_values(payload: AdminPokemonCreate) -> dict[str, Any]:
        values = {field: getattr(payload, field) for field in CORE_FIELDS}
        for field in ("height_m", "weight_kg"):
            if values[field] is not None:
                values[field] = Decimal(str(values[field]))
        return values

    def _sync_types(self, pokemon: Pokemon, type_codes: list[str]) -> None:
        normalized = [code.strip().casefold() for code in type_codes]
        rows = list(
            self.session.scalars(
                select(Type).where(func.lower(Type.code).in_(normalized))
            )
        )
        by_code = {item.code.casefold(): item for item in rows}
        missing = [code for code in normalized if code not in by_code]
        if missing:
            raise ValueError(f"unknown Pokémon type codes: {', '.join(missing)}")
        current = [
            link.type_record.code.casefold()
            for link in sorted(pokemon.type_links, key=lambda item: item.slot)
        ]
        if current == normalized:
            return
        pokemon.type_links.clear()
        self.session.flush()
        for slot, code in enumerate(normalized, start=1):
            pokemon.type_links.append(
                PokemonType(slot=slot, type_record=by_code[code])
            )

    @staticmethod
    def _sync_stats(pokemon: Pokemon, payload) -> None:
        if payload is None:
            pokemon.stats = None
            return
        values = payload.model_dump()
        if pokemon.stats is None:
            pokemon.stats = PokemonStats(**values)
            return
        for field, value in values.items():
            setattr(pokemon.stats, field, value)

    def _sync_descriptions(self, pokemon: Pokemon, payloads: list) -> None:
        existing = {
            (item.language_code, item.description_kind, item.source_key): item
            for item in pokemon.descriptions
        }
        desired_keys = {
            (item.language_code, item.description_kind, item.source_key)
            for item in payloads
        }
        changed_sources: set[str] = set()

        # Avoid transient partial-unique conflicts when the primary item changes.
        for item in existing.values():
            item.is_primary = False
        if existing:
            self.session.flush()

        for key, item in existing.items():
            if key not in desired_keys:
                changed_sources.add(item.source_key.removeprefix("csv:"))
                self.session.delete(item)

        for payload in payloads:
            key = (
                payload.language_code,
                payload.description_kind,
                payload.source_key,
            )
            digest = content_hash(payload.content)
            item = existing.get(key)
            if item is None:
                pokemon.descriptions.append(
                    PokemonDescription(
                        language_code=payload.language_code,
                        description_kind=payload.description_kind,
                        source_key=payload.source_key,
                        content=payload.content,
                        content_hash=digest,
                        is_primary=payload.is_primary,
                    )
                )
                changed_sources.add(payload.source_key.removeprefix("csv:"))
                continue
            if item.content_hash != digest:
                changed_sources.add(item.source_key.removeprefix("csv:"))
            item.content = payload.content
            item.content_hash = digest
            item.is_primary = payload.is_primary

        if changed_sources and pokemon.id is not None:
            self._mark_knowledge_stale(pokemon.id, changed_sources)

    def _sync_images(self, pokemon: Pokemon, payloads: list) -> None:
        existing = {item.image_kind: item for item in pokemon.images}
        desired = {item.image_kind for item in payloads}
        for item in existing.values():
            item.is_primary = False
        if existing:
            self.session.flush()
        for kind, item in existing.items():
            if kind not in desired:
                self.session.delete(item)
        for payload in payloads:
            item = existing.get(payload.image_kind)
            if item is None:
                pokemon.images.append(
                    PokemonImage(
                        image_kind=payload.image_kind,
                        image_url=str(payload.image_url),
                        is_primary=payload.is_primary,
                    )
                )
                continue
            item.image_url = str(payload.image_url)
            item.is_primary = payload.is_primary

    def _mark_knowledge_stale(
        self,
        pokemon_id: int,
        source_keys: set[str],
    ) -> None:
        document_ids = select(PokemonKnowledgeDocument.id).where(
            PokemonKnowledgeDocument.pokemon_id == pokemon_id,
            PokemonKnowledgeDocument.source_key.in_(source_keys),
            PokemonKnowledgeDocument.is_current.is_(True),
        )
        self.session.execute(
            update(PokemonKnowledgeChunk)
            .where(
                PokemonKnowledgeChunk.document_id.in_(document_ids),
                PokemonKnowledgeChunk.is_current.is_(True),
            )
            .values(is_current=False, status="stale")
        )
        self.session.execute(
            update(PokemonKnowledgeDocument)
            .where(PokemonKnowledgeDocument.id.in_(document_ids))
            .values(is_current=False, status="stale", updated_at=func.now())
        )
