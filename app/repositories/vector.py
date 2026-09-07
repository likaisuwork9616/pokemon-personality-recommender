"""Persistence and exact pgvector search for knowledge-chunk embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
import os
from typing import Literal, Sequence
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
    document_kind: str
    language_code: str
    content: str
    content_hash: str
    semantic_score: float


@dataclass(frozen=True)
class VectorSearchConfig:
    """Runtime controls for exact or HNSW-backed nearest-neighbour search."""

    mode: Literal["exact", "hnsw"] = "hnsw"
    ef_search: int = 100
    iterative_scan: Literal["strict_order", "relaxed_order"] = "strict_order"

    def __post_init__(self) -> None:
        if self.mode not in {"exact", "hnsw"}:
            raise ValueError("vector search mode must be exact or hnsw")
        if not 1 <= self.ef_search <= 1000:
            raise ValueError("HNSW ef_search must be between 1 and 1000")
        if self.iterative_scan not in {"strict_order", "relaxed_order"}:
            raise ValueError(
                "HNSW iterative scan must be strict_order or relaxed_order"
            )

    @classmethod
    def from_env(cls) -> "VectorSearchConfig":
        return cls(
            mode=os.getenv("PGVECTOR_SEARCH_MODE", "hnsw").strip().casefold(),
            ef_search=int(os.getenv("HNSW_EF_SEARCH", "100")),
            iterative_scan=os.getenv(
                "HNSW_ITERATIVE_SCAN", "strict_order"
            ).strip().casefold(),
        )


class VectorRepository:
    """Store vectors and query them while enforcing knowledge visibility rules."""

    def __init__(
        self,
        session: Session,
        *,
        search_config: VectorSearchConfig | None = None,
    ) -> None:
        self.session = session
        self.search_config = search_config or VectorSearchConfig.from_env()

    def _configure_vector_scan(self) -> None:
        """Apply transaction-local planner and pgvector settings."""

        if self.search_config.mode == "exact":
            settings = {
                "enable_indexscan": "off",
                "enable_bitmapscan": "off",
                "enable_seqscan": "on",
            }
        else:
            settings = {
                "enable_indexscan": "on",
                "enable_bitmapscan": "on",
                "enable_seqscan": "on",
                "hnsw.ef_search": str(self.search_config.ef_search),
                "hnsw.iterative_scan": self.search_config.iterative_scan,
            }
        for name, value in settings.items():
            self.session.execute(select(func.set_config(name, value, True)))

    def active_model(self) -> EmbeddingModel:
        """Return the one configured active model for startup preflight."""

        statement = (
            select(EmbeddingModel)
            .where(EmbeddingModel.is_active.is_(True))
            .order_by(EmbeddingModel.id)
            .limit(2)
        )
        models = list(self.session.scalars(statement))
        if not models:
            raise RuntimeError("No active embedding model is configured")
        if len(models) > 1:
            raise RuntimeError("Multiple active embedding models are configured")
        model = models[0]
        if model.dimensions != 384:
            raise RuntimeError("Active embedding model must have 384 dimensions")
        return model

    def ready_pokemon_count(self, embedding_model_id: int) -> int:
        """Count active Pokémon that have at least one current ready vector."""

        statement = (
            select(func.count(func.distinct(Pokemon.id)))
            .select_from(PokemonChunkEmbedding)
            .join(EmbeddingModel)
            .join(PokemonKnowledgeChunk)
            .join(PokemonKnowledgeDocument)
            .join(Pokemon)
            .where(
                PokemonChunkEmbedding.embedding_model_id == embedding_model_id,
                EmbeddingModel.id == embedding_model_id,
                EmbeddingModel.is_active.is_(True),
                EmbeddingModel.normalize_embeddings.is_(True),
                PokemonChunkEmbedding.status == "ready",
                PokemonChunkEmbedding.embedding.is_not(None),
                PokemonChunkEmbedding.content_hash == PokemonKnowledgeChunk.content_hash,
                PokemonKnowledgeChunk.is_current.is_(True),
                PokemonKnowledgeChunk.status == "ready",
                PokemonKnowledgeDocument.is_current.is_(True),
                PokemonKnowledgeDocument.status == "ready",
                Pokemon.is_active.is_(True),
            )
        )
        return int(self.session.scalar(statement) or 0)

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
        """Return cosine-nearest chunks using the configured planner mode."""

        vector = [float(value) for value in query_vector]
        if len(vector) != 384 or not all(isfinite(value) for value in vector):
            raise ValueError("query_vector must contain 384 finite values")
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")

        self._configure_vector_scan()
        distance = PokemonChunkEmbedding.embedding.cosine_distance(vector)
        statement = (
            select(
                Pokemon.id,
                PokemonKnowledgeDocument.id,
                PokemonKnowledgeChunk.id,
                PokemonKnowledgeDocument.source_key,
                PokemonKnowledgeDocument.document_kind,
                PokemonKnowledgeDocument.language_code,
                PokemonKnowledgeChunk.content,
                PokemonKnowledgeChunk.content_hash,
                (1.0 - distance).label("semantic_score"),
            )
            .select_from(PokemonChunkEmbedding)
            .join(EmbeddingModel)
            .join(PokemonKnowledgeChunk)
            .join(PokemonKnowledgeDocument)
            .join(Pokemon)
            .where(
                PokemonChunkEmbedding.embedding_model_id == embedding_model_id,
                EmbeddingModel.id == embedding_model_id,
                EmbeddingModel.is_active.is_(True),
                EmbeddingModel.dimensions == 384,
                EmbeddingModel.normalize_embeddings.is_(True),
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
                document_kind=row[4],
                language_code=row[5],
                content=row[6],
                content_hash=row[7],
                semantic_score=float(row[8]),
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
