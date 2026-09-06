"""Persistence operations for the imported Pokemon aggregate."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Mapping
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
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
from app.services.knowledge import (
    build_knowledge_documents,
    split_knowledge_document,
)

if TYPE_CHECKING:
    from app.services.csv_importer import ParsedPokemonRow, TypeDefinition


class PokemonRepository:
    """Store and query Pokemon aggregates within a caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def count(self) -> int:
        return int(self.session.scalar(select(func.count(Pokemon.id))) or 0)

    def get_by_natural_key(
        self, pokedex_number: int, form_key: str = "default"
    ) -> Pokemon | None:
        return self.session.scalar(
            select(Pokemon).where(
                Pokemon.pokedex_number == pokedex_number,
                Pokemon.form_key == form_key,
            )
        )

    def list_active(self, *, offset: int = 0, limit: int = 100) -> list[Pokemon]:
        statement = (
            select(Pokemon)
            .where(Pokemon.is_active.is_(True))
            .order_by(Pokemon.pokedex_number, Pokemon.form_key, Pokemon.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def search_catalog(
        self,
        *,
        q: str | None = None,
        page: int = 1,
        page_size: int = 20,
        type_code: str | None = None,
        generation: int | None = None,
        is_legendary: bool | None = None,
        is_mythical: bool | None = None,
    ) -> tuple[list[Pokemon], int]:
        """Return one active-only catalog page and its unpaginated count."""

        filters = [Pokemon.is_active.is_(True)]
        normalized_query = (q or "").strip()
        if normalized_query:
            escaped = (
                normalized_query.replace("\\", "\\\\")
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
        if generation is not None:
            filters.append(Pokemon.generation == generation)
        if is_legendary is not None:
            filters.append(Pokemon.is_legendary.is_(is_legendary))
        if is_mythical is not None:
            filters.append(Pokemon.is_mythical.is_(is_mythical))

        normalized_type = (type_code or "").strip()
        if normalized_type:
            type_value = normalized_type.casefold()
            filters.append(
                select(PokemonType.pokemon_id)
                .join(Type, Type.id == PokemonType.type_id)
                .where(
                    PokemonType.pokemon_id == Pokemon.id,
                    or_(
                        func.lower(Type.code) == type_value,
                        func.lower(Type.name_en) == type_value,
                        Type.name_zh == normalized_type,
                    ),
                )
                .exists()
            )

        total = int(
            self.session.scalar(
                select(func.count(Pokemon.id)).where(*filters)
            )
            or 0
        )
        statement = (
            select(Pokemon)
            .where(*filters)
            .options(
                selectinload(Pokemon.type_links).selectinload(
                    PokemonType.type_record
                ),
                selectinload(Pokemon.images),
            )
            .order_by(Pokemon.pokedex_number, Pokemon.form_key, Pokemon.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.session.scalars(statement).unique()), total

    def get_catalog_detail(self, pokemon_id: int) -> Pokemon | None:
        """Load one active Pokemon and every relation needed by its detail page."""

        statement = (
            select(Pokemon)
            .where(Pokemon.id == pokemon_id, Pokemon.is_active.is_(True))
            .options(
                selectinload(Pokemon.type_links).selectinload(
                    PokemonType.type_record
                ),
                selectinload(Pokemon.stats),
                selectinload(Pokemon.descriptions),
                selectinload(Pokemon.images),
            )
        )
        return self.session.scalar(statement)

    def recommender_records(self) -> list[dict[str, object]]:
        """Return the active catalog in the legacy engine's tabular contract.

        PostgreSQL remains the source of truth while the vector-search chapter
        replaces the temporary in-process embedding calculation.
        """

        statement = (
            select(Pokemon)
            .where(Pokemon.is_active.is_(True))
            .options(
                selectinload(Pokemon.type_links).selectinload(PokemonType.type_record),
                selectinload(Pokemon.stats),
                selectinload(Pokemon.descriptions),
                selectinload(Pokemon.images),
            )
            .order_by(Pokemon.pokedex_number, Pokemon.form_key, Pokemon.id)
        )
        records: list[dict[str, object]] = []
        for pokemon in self.session.scalars(statement).unique():
            type_links = sorted(pokemon.type_links, key=lambda link: link.slot)
            descriptions = {
                item.source_key.removeprefix("csv:"): item.content
                for item in pokemon.descriptions
            }
            images = {item.image_kind: item.image_url for item in pokemon.images}
            stats = pokemon.stats
            record: dict[str, object] = {
                "_database_id": pokemon.id,
                "pokedex_number": pokemon.pokedex_number,
                "name_zh": pokemon.name_zh,
                "name_en": pokemon.name_en,
                "type_zh": ", ".join(link.type_record.name_zh for link in type_links),
                "type_1": type_links[0].type_record.name_en if type_links else "Unknown",
                "type_2": type_links[1].type_record.name_en if len(type_links) > 1 else "Unknown",
                "category_zh": pokemon.category_zh or "",
                "genus": pokemon.genus or "",
                "description_zh": descriptions.get("description_zh", ""),
                "flavor_text_en": descriptions.get("flavor_text_en", ""),
                "analysis_text": descriptions.get("analysis_text", ""),
                "image_url": images.get("artwork", ""),
                "sprite_url": images.get("sprite", ""),
                "height_m": pokemon.height_m,
                "weight_kg": pokemon.weight_kg,
                "abilities": pokemon.abilities,
                "hidden_ability": pokemon.hidden_ability or "Unknown",
                "generation": pokemon.generation,
                "is_legendary": pokemon.is_legendary,
                "is_mythical": pokemon.is_mythical,
                "is_baby": pokemon.is_baby,
                "color": pokemon.color or "",
                "shape": pokemon.shape or "",
                "egg_groups": pokemon.egg_groups,
                "habitat": pokemon.habitat or "Unknown",
                "growth_rate": pokemon.growth_rate or "",
                "capture_rate": pokemon.capture_rate,
                "is_outlier": pokemon.is_outlier,
                "lof_outlier": pokemon.lof_outlier,
            }
            for field in (
                "hp", "attack", "defense", "sp_attack", "sp_defense", "speed",
                "base_stat_total", "scaled_hp", "scaled_attack", "scaled_defense",
                "scaled_sp_attack", "scaled_sp_defense", "scaled_speed",
                "scaled_height_m", "scaled_weight_kg",
            ):
                record[field] = getattr(stats, field) if stats is not None else None
            records.append(record)
        return records

    def seed_types(
        self, definitions: Mapping[str, TypeDefinition]
    ) -> dict[str, int]:
        """Upsert the canonical type lookup and return IDs keyed by type code."""

        for definition in definitions.values():
            base = insert(Type).values(
                code=definition.code,
                name_en=definition.name_en,
                name_zh=definition.name_zh,
            )
            statement = base.on_conflict_do_update(
                constraint="uq_types_code",
                set_={
                    "name_en": base.excluded.name_en,
                    "name_zh": base.excluded.name_zh,
                },
                where=or_(
                    Type.name_en.is_distinct_from(base.excluded.name_en),
                    Type.name_zh.is_distinct_from(base.excluded.name_zh),
                ),
            )
            self.session.execute(statement)

        rows = self.session.execute(
            select(Type.code, Type.id).where(Type.code.in_(definitions.keys()))
        )
        type_ids = {code: type_id for code, type_id in rows}
        missing = set(definitions) - set(type_ids)
        if missing:
            raise RuntimeError(f"Failed to seed Pokemon types: {sorted(missing)}")
        return type_ids

    def upsert_record(
        self,
        record: ParsedPokemonRow,
        type_ids: Mapping[str, int],
    ) -> int:
        """Upsert one parent row and every CSV-owned child record."""

        pokemon_id = self._upsert_pokemon(record)
        self._sync_types(pokemon_id, record.type_codes, type_ids)
        self._upsert_stats(pokemon_id, record)
        self._upsert_descriptions(pokemon_id, record)
        self._upsert_images(pokemon_id, record)
        self._sync_knowledge(pokemon_id, record)
        return pokemon_id

    def _upsert_pokemon(self, record: ParsedPokemonRow) -> int:
        values = asdict(record.pokemon)
        natural_key = (
            record.pokemon.pokedex_number,
            record.pokemon.form_key,
        )
        existing_id = self.session.scalar(
            select(Pokemon.id).where(
                Pokemon.pokedex_number == natural_key[0],
                Pokemon.form_key == natural_key[1],
            )
        )

        base = insert(Pokemon).values(**values)
        mutable_columns = tuple(
            key for key in values if key not in {"pokedex_number", "form_key"}
        )
        statement = base.on_conflict_do_update(
            constraint="uq_pokemon_dex_form",
            set_={
                **{name: getattr(base.excluded, name) for name in mutable_columns},
                "updated_at": func.now(),
            },
            where=or_(
                *(
                    getattr(Pokemon, name).is_distinct_from(
                        getattr(base.excluded, name)
                    )
                    for name in mutable_columns
                )
            ),
        ).returning(Pokemon.id)
        pokemon_id = self.session.scalar(statement)
        if pokemon_id is not None:
            return int(pokemon_id)
        if existing_id is None:
            raise RuntimeError(f"Pokemon UPSERT returned no ID for {natural_key}")
        return int(existing_id)

    def _sync_types(
        self,
        pokemon_id: int,
        type_codes: tuple[str, ...],
        type_ids: Mapping[str, int],
    ) -> None:
        desired = {slot: type_ids[code] for slot, code in enumerate(type_codes, 1)}
        self.session.execute(
            delete(PokemonType).where(
                PokemonType.pokemon_id == pokemon_id,
                or_(
                    PokemonType.slot.not_in(desired),
                    *(
                        (PokemonType.slot == slot)
                        & (PokemonType.type_id != type_id)
                        for slot, type_id in desired.items()
                    ),
                ),
            )
        )
        for slot, type_id in desired.items():
            statement = (
                insert(PokemonType)
                .values(pokemon_id=pokemon_id, type_id=type_id, slot=slot)
                .on_conflict_do_nothing()
            )
            self.session.execute(statement)

    def _upsert_stats(self, pokemon_id: int, record: ParsedPokemonRow) -> None:
        values = {"pokemon_id": pokemon_id, **asdict(record.stats)}
        base = insert(PokemonStats).values(**values)
        mutable_columns = tuple(key for key in values if key != "pokemon_id")
        statement = base.on_conflict_do_update(
            index_elements=[PokemonStats.pokemon_id],
            set_={name: getattr(base.excluded, name) for name in mutable_columns},
            where=or_(
                *(
                    getattr(PokemonStats, name).is_distinct_from(
                        getattr(base.excluded, name)
                    )
                    for name in mutable_columns
                )
            ),
        )
        self.session.execute(statement)

    def _upsert_descriptions(
        self, pokemon_id: int, record: ParsedPokemonRow
    ) -> None:
        for description in record.descriptions:
            values = {"pokemon_id": pokemon_id, **asdict(description)}
            base = insert(PokemonDescription).values(**values)
            mutable_columns = ("content", "content_hash", "is_primary")
            statement = base.on_conflict_do_update(
                constraint="uq_pokemon_description_source",
                set_={
                    **{
                        name: getattr(base.excluded, name)
                        for name in mutable_columns
                    },
                    "updated_at": func.now(),
                },
                where=or_(
                    *(
                        getattr(PokemonDescription, name).is_distinct_from(
                            getattr(base.excluded, name)
                        )
                        for name in mutable_columns
                    )
                ),
            )
            self.session.execute(statement)

    def _upsert_images(self, pokemon_id: int, record: ParsedPokemonRow) -> None:
        for image in record.images:
            values = {"pokemon_id": pokemon_id, **asdict(image)}
            base = insert(PokemonImage).values(**values)
            mutable_columns = ("image_url", "is_primary")
            statement = base.on_conflict_do_update(
                constraint="uq_pokemon_image_kind",
                set_={name: getattr(base.excluded, name) for name in mutable_columns},
                where=or_(
                    *(
                        getattr(PokemonImage, name).is_distinct_from(
                            getattr(base.excluded, name)
                        )
                        for name in mutable_columns
                    )
                ),
            )
            self.session.execute(statement)

    def _sync_knowledge(self, pokemon_id: int, record: ParsedPokemonRow) -> None:
        """Version derived documents and make their deterministic chunks current."""

        type_names = dict(
            self.session.execute(
                select(Type.code, Type.name_zh).where(Type.code.in_(record.type_codes))
            )
        )
        description_contents = {
            item.source_key.removeprefix("csv:"): item.content
            for item in record.descriptions
        }
        source_record: dict[str, object] = {
            **asdict(record.pokemon),
            "type_zh": ", ".join(type_names[code] for code in record.type_codes),
            **description_contents,
        }

        description_ids = {
            source_key.removeprefix("csv:"): description_id
            for source_key, description_id in self.session.execute(
                select(PokemonDescription.source_key, PokemonDescription.id).where(
                    PokemonDescription.pokemon_id == pokemon_id
                )
            )
        }
        current_documents = list(
            self.session.scalars(
                select(PokemonKnowledgeDocument).where(
                    PokemonKnowledgeDocument.pokemon_id == pokemon_id,
                    PokemonKnowledgeDocument.is_current.is_(True),
                )
            )
        )
        current_by_source = {
            document.source_key: document for document in current_documents
        }
        latest_versions = dict(
            self.session.execute(
                select(
                    PokemonKnowledgeDocument.source_key,
                    func.max(PokemonKnowledgeDocument.version),
                )
                .where(PokemonKnowledgeDocument.pokemon_id == pokemon_id)
                .group_by(PokemonKnowledgeDocument.source_key)
            )
        )

        provisional = build_knowledge_documents(source_record)
        versions = {
            document.source_key: (
                current_by_source[document.source_key].version
                if document.source_key in current_by_source
                and current_by_source[document.source_key].content_hash
                == document.content_hash
                else int(latest_versions.get(document.source_key, 0)) + 1
            )
            for document in provisional
        }
        desired_documents = build_knowledge_documents(
            source_record,
            versions=versions,
        )
        desired_sources = {document.source_key for document in desired_documents}

        for old_document in current_documents:
            replacement = next(
                (
                    document
                    for document in desired_documents
                    if document.source_key == old_document.source_key
                ),
                None,
            )
            if (
                old_document.source_key not in desired_sources
                or replacement is None
                or old_document.content_hash != replacement.content_hash
            ):
                self._mark_document_stale(old_document.id)

        for document in desired_documents:
            document_id = UUID(document.document_id)
            values = {
                "id": document_id,
                "pokemon_id": pokemon_id,
                "source_description_id": description_ids.get(document.source_key),
                "source_key": document.source_key,
                "document_kind": document.document_kind,
                "language_code": document.language,
                "content": document.content,
                "content_hash": document.content_hash,
                "version": document.version,
                "is_current": True,
                "status": "ready",
            }
            base = insert(PokemonKnowledgeDocument).values(**values)
            statement = base.on_conflict_do_update(
                index_elements=[PokemonKnowledgeDocument.id],
                set_={
                    "source_description_id": base.excluded.source_description_id,
                    "is_current": True,
                    "status": "ready",
                    "updated_at": func.now(),
                },
            )
            self.session.execute(statement)
            self._sync_chunks(document_id, document)

    def _mark_document_stale(self, document_id: UUID) -> None:
        self.session.execute(
            update(PokemonKnowledgeDocument)
            .where(PokemonKnowledgeDocument.id == document_id)
            .values(is_current=False, status="stale", updated_at=func.now())
        )
        self.session.execute(
            update(PokemonKnowledgeChunk)
            .where(
                PokemonKnowledgeChunk.document_id == document_id,
                PokemonKnowledgeChunk.is_current.is_(True),
            )
            .values(is_current=False, status="stale")
        )

    def _sync_chunks(self, document_id: UUID, document) -> None:
        chunks = split_knowledge_document(document)
        desired_ids = {UUID(chunk.chunk_id) for chunk in chunks}
        existing_current = list(
            self.session.scalars(
                select(PokemonKnowledgeChunk).where(
                    PokemonKnowledgeChunk.document_id == document_id,
                    PokemonKnowledgeChunk.is_current.is_(True),
                )
            )
        )
        for old_chunk in existing_current:
            if old_chunk.id not in desired_ids:
                self.session.execute(
                    update(PokemonKnowledgeChunk)
                    .where(PokemonKnowledgeChunk.id == old_chunk.id)
                    .values(is_current=False, status="stale")
                )

        for chunk in chunks:
            values = {
                "id": UUID(chunk.chunk_id),
                "document_id": document_id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "lexical_text": chunk.lexical_text,
                "content_hash": chunk.content_hash,
                "char_count": chunk.char_count,
                "token_count": chunk.token_count,
                "is_current": True,
                "status": "ready",
            }
            base = insert(PokemonKnowledgeChunk).values(**values)
            statement = base.on_conflict_do_update(
                index_elements=[PokemonKnowledgeChunk.id],
                set_={
                    "lexical_text": base.excluded.lexical_text,
                    "char_count": base.excluded.char_count,
                    "token_count": base.excluded.token_count,
                    "is_current": True,
                    "status": "ready",
                },
            )
            self.session.execute(statement)
