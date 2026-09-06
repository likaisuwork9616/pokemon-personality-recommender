"""Persistence and exact pgvector search for knowledge-chunk embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Sequence
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import (
    EmbeddingModel,
    Pokemon,
    PokemonChunkEmbedding,
    PokemonKnowledgeChunk,
    PokemonKnowledgeDocument,
)


@dataclass(frozen=True)
class EmbeddingCandidate:
    chunk_id: UUID
    content: str
    content_hash: str


@dataclass(frozen=True)
class VectorSearchHit:
    rank: int
    pokemon_id: int
    document_id: UUID
    chunk_id: UUID
    source_key: str
    content: str
    semantic_score: float


class VectorRepository:
    """Store vectors and query them while enforcing knowledge visibility rules."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def ensure_model(
        self,
        *,
        model_name: str,
        model_version: str,
        dimensions: int = 384,
        normalize_embeddings: bool = True,
        activate: bool = True,
    ) -> EmbeddingModel:
        if dimensions != 384:
            raise ValueError("pokemon_chunk_embeddings requires exactly 384 dimensions")
        if activate:
            self.session.execute(
                update(EmbeddingModel)
                .where(EmbeddingModel.is_active.is_(True))
                .values(is_active=False)
            )

        base = insert(EmbeddingModel).values(
            model_name=model_name.strip(),
            model_version=model_version.strip(),
            dimensions=dimensions,
            normalize_embeddings=normalize_embeddings,
            is_active=activate,
        )
        statement = base.on_conflict_do_update(
            constraint="uq_embedding_model_identity",
            set_={
                "dimensions": base.excluded.dimensions,
                "normalize_embeddings": base.excluded.normalize_embeddings,
                "is_active": base.excluded.is_active,
            },
        ).returning(EmbeddingModel.id)
        model_id = self.session.scalar(statement)
        if model_id is None:
            raise RuntimeError("Embedding model UPSERT returned no ID")
        model = self.session.get(EmbeddingModel, model_id)
        if model is None:
            raise RuntimeError("Embedding model could not be reloaded")
        return model

    def pending_chunks(self, embedding_model_id: int) -> list[EmbeddingCandidate]:
        """Return eligible chunks missing a matching ready vector."""

        statement = (
            select(
                PokemonKnowledgeChunk.id,
                PokemonKnowledgeChunk.content,
                PokemonKnowledgeChunk.content_hash,
            )
            .select_from(PokemonKnowledgeChunk)
            .join(PokemonKnowledgeDocument)
            .join(Pokemon)
            .outerjoin(
                PokemonChunkEmbedding,
                and_(
                    PokemonChunkEmbedding.chunk_id == PokemonKnowledgeChunk.id,
                    PokemonChunkEmbedding.embedding_model_id == embedding_model_id,
                ),
            )
            .where(
                Pokemon.is_active.is_(True),
                PokemonKnowledgeDocument.is_current.is_(True),
                PokemonKnowledgeDocument.status == "ready",
                PokemonKnowledgeChunk.is_current.is_(True),
                PokemonKnowledgeChunk.status == "ready",
                or_(
                    PokemonChunkEmbedding.chunk_id.is_(None),
                    PokemonChunkEmbedding.status != "ready",
                    PokemonChunkEmbedding.embedding.is_(None),
                    PokemonChunkEmbedding.content_hash.is_distinct_from(
                        PokemonKnowledgeChunk.content_hash
                    ),
                ),
            )
            .order_by(
                Pokemon.pokedex_number,
                Pokemon.form_key,
                PokemonKnowledgeDocument.source_key,
                PokemonKnowledgeDocument.version,
                PokemonKnowledgeChunk.chunk_index,
                PokemonKnowledgeChunk.id,
            )
        )
        return [EmbeddingCandidate(*row) for row in self.session.execute(statement)]

    def save_ready(
        self,
        *,
        candidate: EmbeddingCandidate,
        embedding_model_id: int,
        embedding: Sequence[float],
    ) -> None:
        values = {
            "chunk_id": candidate.chunk_id,
            "embedding_model_id": embedding_model_id,
            "embedding": list(embedding),
            "content_hash": candidate.content_hash,
            "status": "ready",
            "last_error": None,
            "embedded_at": func.now(),
            "updated_at": func.now(),
        }
        base = insert(PokemonChunkEmbedding).values(**values)
        self.session.execute(
            base.on_conflict_do_update(
                index_elements=[
                    PokemonChunkEmbedding.chunk_id,
                    PokemonChunkEmbedding.embedding_model_id,
                ],
                set_={key: getattr(base.excluded, key) for key in values if key not in {
                    "chunk_id",
                    "embedding_model_id",
                }},
            )
        )

    def save_failed(
        self,
        *,
        candidate: EmbeddingCandidate,
        embedding_model_id: int,
        error: str,
    ) -> None:
        values = {
            "chunk_id": candidate.chunk_id,
            "embedding_model_id": embedding_model_id,
            "embedding": None,
            "content_hash": candidate.content_hash,
            "status": "failed",
            "last_error": error[:2000],
            "embedded_at": None,
            "updated_at": func.now(),
        }
        base = insert(PokemonChunkEmbedding).values(**values)
        self.session.execute(
            base.on_conflict_do_update(
                index_elements=[
                    PokemonChunkEmbedding.chunk_id,
                    PokemonChunkEmbedding.embedding_model_id,
                ],
                set_={key: getattr(base.excluded, key) for key in values if key not in {
                    "chunk_id",
                    "embedding_model_id",
                }},
            )
        )

    def exact_search(
        self,
        *,
        query_vector: Sequence[float],
        embedding_model_id: int,
        limit: int = 50,
    ) -> list[VectorSearchHit]:
        """Return exact cosine-nearest current chunks with stable tie-breaking."""

        vector = [float(value) for value in query_vector]
        if len(vector) != 384 or not all(isfinite(value) for value in vector):
            raise ValueError("query_vector must contain 384 finite values")
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")

        distance = PokemonChunkEmbedding.embedding.cosine_distance(vector)
        statement = (
            select(
                Pokemon.id,
                PokemonKnowledgeDocument.id,
                PokemonKnowledgeChunk.id,
                PokemonKnowledgeDocument.source_key,
                PokemonKnowledgeChunk.content,
                (1.0 - distance).label("semantic_score"),
            )
            .select_from(PokemonChunkEmbedding)
            .join(PokemonKnowledgeChunk)
            .join(PokemonKnowledgeDocument)
            .join(Pokemon)
            .where(
                PokemonChunkEmbedding.embedding_model_id == embedding_model_id,
                PokemonChunkEmbedding.status == "ready",
                PokemonChunkEmbedding.embedding.is_not(None),
                PokemonChunkEmbedding.content_hash == PokemonKnowledgeChunk.content_hash,
                PokemonKnowledgeChunk.is_current.is_(True),
                PokemonKnowledgeChunk.status == "ready",
                PokemonKnowledgeDocument.is_current.is_(True),
                PokemonKnowledgeDocument.status == "ready",
                Pokemon.is_active.is_(True),
            )
            .order_by(distance, PokemonKnowledgeChunk.id)
            .limit(limit)
        )
        return [
            VectorSearchHit(
                rank=rank,
                pokemon_id=int(row[0]),
                document_id=row[1],
                chunk_id=row[2],
                source_key=row[3],
                content=row[4],
                semantic_score=float(row[5]),
            )
            for rank, row in enumerate(self.session.execute(statement), start=1)
        ]

    def active_pokemon_embeddings(self) -> dict[int, list[list[float]]]:
        """Load stored current vectors grouped by active Pokémon.

        This temporary compatibility adapter prevents the legacy recommender
        from re-encoding the full corpus while Hybrid Retrieval is introduced.
        """

        statement = (
            select(Pokemon.id, PokemonChunkEmbedding.embedding)
            .select_from(PokemonChunkEmbedding)
            .join(EmbeddingModel)
            .join(PokemonKnowledgeChunk)
            .join(PokemonKnowledgeDocument)
            .join(Pokemon)
            .where(
                EmbeddingModel.is_active.is_(True),
                PokemonChunkEmbedding.status == "ready",
                PokemonChunkEmbedding.embedding.is_not(None),
                PokemonChunkEmbedding.content_hash == PokemonKnowledgeChunk.content_hash,
                PokemonKnowledgeChunk.is_current.is_(True),
                PokemonKnowledgeChunk.status == "ready",
                PokemonKnowledgeDocument.is_current.is_(True),
                PokemonKnowledgeDocument.status == "ready",
                Pokemon.is_active.is_(True),
            )
            .order_by(Pokemon.id, PokemonKnowledgeChunk.id)
        )
        grouped: dict[int, list[list[float]]] = {}
        for pokemon_id, embedding in self.session.execute(statement):
            grouped.setdefault(int(pokemon_id), []).append(list(embedding))
        return grouped
