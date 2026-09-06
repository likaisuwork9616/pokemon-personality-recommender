"""Incremental, injectable SentenceTransformer embedding pipeline."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from math import isfinite, sqrt
from typing import Protocol

from app.repositories.vector import EmbeddingCandidate, VectorRepository


DEFAULT_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


class SentenceEncoder(Protocol):
    def encode(self, sentences: Sequence[str], **kwargs): ...


@dataclass(frozen=True)
class EmbeddingConfig:
    model_name: str = DEFAULT_MODEL_NAME
    model_version: str = "default"
    dimensions: int = 384
    normalize_embeddings: bool = True
    batch_size: int = 64

    def __post_init__(self) -> None:
        if not self.model_name.strip() or not self.model_version.strip():
            raise ValueError("model name and version must not be blank")
        if self.dimensions != 384:
            raise ValueError("the MVP embedding table requires 384 dimensions")
        if self.batch_size < 1:
            raise ValueError("batch_size must be positive")


@dataclass(frozen=True)
class EmbeddingBuildSummary:
    embedding_model_id: int
    discovered: int
    embedded: int
    failed: int


@lru_cache(maxsize=2)
def default_encoder_factory(model_name: str) -> SentenceEncoder:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def validate_embedding_vector(values, dimensions: int) -> list[float]:
    vector = [float(value) for value in values]
    if len(vector) != dimensions or not all(isfinite(value) for value in vector):
        raise ValueError(f"encoder must return {dimensions} finite values per chunk")
    norm = sqrt(sum(value * value for value in vector))
    if norm == 0:
        raise ValueError("encoder returned a zero vector")
    return [value / norm for value in vector]


class EmbeddingService:
    """Build only missing, failed, stale, or hash-mismatched eligible vectors."""

    def __init__(
        self,
        repository: VectorRepository,
        *,
        config: EmbeddingConfig | None = None,
        encoder_factory: Callable[[str], SentenceEncoder] = default_encoder_factory,
    ) -> None:
        self.repository = repository
        self.config = config or EmbeddingConfig()
        self.encoder_factory = encoder_factory

    def rebuild(self) -> EmbeddingBuildSummary:
        model = self.repository.ensure_model(
            model_name=self.config.model_name,
            model_version=self.config.model_version,
            dimensions=self.config.dimensions,
            normalize_embeddings=self.config.normalize_embeddings,
            activate=True,
        )
        candidates = self.repository.pending_chunks(model.id)
        if not candidates:
            return EmbeddingBuildSummary(model.id, 0, 0, 0)

        try:
            encoder = self.encoder_factory(self.config.model_name)
        except Exception as exc:
            error = self._safe_error(exc)
            for candidate in candidates:
                self.repository.save_failed(
                    candidate=candidate,
                    embedding_model_id=model.id,
                    error=error,
                )
            return EmbeddingBuildSummary(model.id, len(candidates), 0, len(candidates))

        embedded = 0
        failed = 0
        for start in range(0, len(candidates), self.config.batch_size):
            batch = candidates[start : start + self.config.batch_size]
            try:
                encoded = encoder.encode(
                    [candidate.content for candidate in batch],
                    batch_size=self.config.batch_size,
                    normalize_embeddings=self.config.normalize_embeddings,
                    show_progress_bar=False,
                )
                vectors = list(encoded)
                if len(vectors) != len(batch):
                    raise ValueError("encoder returned a different number of vectors")
                validated = [
                    validate_embedding_vector(vector, self.config.dimensions)
                    for vector in vectors
                ]
            except Exception as exc:
                error = self._safe_error(exc)
                for candidate in batch:
                    self.repository.save_failed(
                        candidate=candidate,
                        embedding_model_id=model.id,
                        error=error,
                    )
                failed += len(batch)
                continue

            for candidate, vector in zip(batch, validated):
                self.repository.save_ready(
                    candidate=candidate,
                    embedding_model_id=model.id,
                    embedding=vector,
                )
                embedded += 1

        return EmbeddingBuildSummary(model.id, len(candidates), embedded, failed)

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        return f"{type(exc).__name__}: {exc}"[:2000]
