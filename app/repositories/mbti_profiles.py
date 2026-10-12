"""Read complete indexed behavior profiles without modifying PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    EmbeddingModel, Pokemon, PokemonChunkEmbedding, PokemonImage, PokemonType,
    PokemonKnowledgeChunk, PokemonKnowledgeDocument, Type,
)
from app.services.mbti_scoring import normalized_embedding


BEHAVIOR_DOCUMENT_KINDS = (
    "description_zh", "flavor_text_en", "analysis_text",
    "description", "flavor_text", "analysis",
)


@dataclass(frozen=True)
class IndexedBehaviorChunk:
    document_id: UUID
    chunk_id: UUID
    source_key: str
    document_kind: str
    language_code: str
    content: str
    content_hash: str
    embedding: tuple[float, ...]


@dataclass(frozen=True)
class IndexedBehaviorProfile:
    text: str
    embedding: tuple[float, ...]
    chunks: tuple[IndexedBehaviorChunk, ...]


class MbtiProfileRepository:
    """Load a bounded candidate batch from the request's indexed snapshot."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def metadata_records(self) -> list[dict[str, object]]:
        """Read display fields without loading editable descriptions or traits."""

        statement = (
            select(
                Pokemon.id, Pokemon.pokedex_number, Pokemon.form_key,
                Pokemon.name_zh, Pokemon.name_en, Pokemon.category_zh, Pokemon.genus,
                PokemonType.slot, Type.name_zh, Type.name_en,
                PokemonImage.image_kind, PokemonImage.image_url,
            )
            .select_from(Pokemon)
            .outerjoin(PokemonType, PokemonType.pokemon_id == Pokemon.id)
            .outerjoin(Type, Type.id == PokemonType.type_id)
            .outerjoin(PokemonImage, PokemonImage.pokemon_id == Pokemon.id)
            .where(Pokemon.is_active.is_(True))
            .order_by(Pokemon.pokedex_number, Pokemon.form_key, Pokemon.id, PokemonType.slot)
        )
        records: dict[int, dict[str, object]] = {}
        types: dict[int, dict[int, tuple[str, str]]] = {}
        for row in self.session.execute(statement):
            pokemon_id = int(row[0])
            record = records.setdefault(pokemon_id, {
                "_database_id": pokemon_id, "pokedex_number": int(row[1]),
                "_form_key": str(row[2]), "name_zh": str(row[3]), "name_en": str(row[4]),
                "category_zh": row[5] or "", "genus": row[6] or "",
                "image_url": "", "sprite_url": "",
            })
            if row[7] is not None:
                types.setdefault(pokemon_id, {})[int(row[7])] = (str(row[8]), str(row[9]))
            if row[10] == "artwork":
                record["image_url"] = row[11] or ""
            elif row[10] == "sprite":
                record["sprite_url"] = row[11] or ""
        for pokemon_id, record in records.items():
            ordered_types = types.get(pokemon_id, {})
            record["type_zh"] = ", ".join(ordered_types[slot][0] for slot in sorted(ordered_types))
            record["type_1"] = ordered_types.get(1, ("", ""))[1]
            record["type_2"] = ordered_types.get(2, ("", ""))[1]
        return list(records.values())

    def load_profiles(
        self, pokemon_ids: Sequence[int], *, embedding_model_id: int,
    ) -> dict[int, IndexedBehaviorProfile]:
        ids = tuple(dict.fromkeys(int(value) for value in pokemon_ids))
        if not ids:
            return {}
        if len(ids) > 100 or any(value < 1 for value in ids):
            raise ValueError("profile batch must contain at most 100 positive IDs")
        statement = (
            select(
                Pokemon.id, PokemonKnowledgeDocument.id,
                PokemonKnowledgeDocument.content,
                PokemonKnowledgeDocument.source_key,
                PokemonKnowledgeDocument.document_kind,
                PokemonKnowledgeDocument.language_code,
                PokemonKnowledgeChunk.id, PokemonKnowledgeChunk.content,
                PokemonKnowledgeChunk.content_hash, PokemonChunkEmbedding.embedding,
            )
            .select_from(PokemonChunkEmbedding)
            .join(EmbeddingModel)
            .join(PokemonKnowledgeChunk)
            .join(PokemonKnowledgeDocument)
            .join(Pokemon)
            .where(
                Pokemon.id.in_(ids), Pokemon.is_active.is_(True),
                PokemonKnowledgeDocument.document_kind.in_(BEHAVIOR_DOCUMENT_KINDS),
                PokemonKnowledgeDocument.is_current.is_(True),
                PokemonKnowledgeDocument.status == "ready",
                PokemonKnowledgeChunk.is_current.is_(True),
                PokemonKnowledgeChunk.status == "ready",
                PokemonChunkEmbedding.embedding_model_id == embedding_model_id,
                EmbeddingModel.id == embedding_model_id,
                EmbeddingModel.is_active.is_(True),
                EmbeddingModel.dimensions == 384,
                EmbeddingModel.normalize_embeddings.is_(True),
                PokemonChunkEmbedding.status == "ready",
                PokemonChunkEmbedding.embedding.is_not(None),
                PokemonChunkEmbedding.content_hash == PokemonKnowledgeChunk.content_hash,
            )
            .order_by(Pokemon.id, PokemonKnowledgeDocument.id, PokemonKnowledgeChunk.chunk_index)
        )
        documents: dict[int, dict[UUID, str]] = {}
        chunks: dict[int, list[IndexedBehaviorChunk]] = {}
        for row in self.session.execute(statement):
            pokemon_id = int(row[0])
            documents.setdefault(pokemon_id, {})[row[1]] = str(row[2])
            embedding = normalized_embedding(row[9])
            chunks.setdefault(pokemon_id, []).append(IndexedBehaviorChunk(
                document_id=row[1], chunk_id=row[6], source_key=str(row[3]),
                document_kind=str(row[4]), language_code=str(row[5]),
                content=str(row[7]), content_hash=str(row[8]),
                embedding=tuple(float(value) for value in embedding),
            ))
        return {
            pokemon_id: IndexedBehaviorProfile(
                text="\n".join(documents[pokemon_id].values()),
                embedding=tuple(float(value) for value in normalized_embedding(
                    np.mean([chunk.embedding for chunk in values], axis=0)
                )),
                chunks=tuple(values),
            )
            for pokemon_id, values in chunks.items()
        }
