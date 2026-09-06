"""Synchronous, retryable per-Pokémon embedding rebuild orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.repositories.reindex import PokemonIndexState, PokemonReindexRepository
from app.repositories.vector import VectorRepository
from app.services.embedding import (
    SentenceEncoder,
    default_encoder_factory,
    validate_embedding_vector,
)


class PokemonNotFoundError(LookupError):
    pass


class ReindexUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class PokemonReindexSummary:
    pokemon_id: int
    embedding_model_id: int
    discovered: int
    embedded: int
    failed: int
    index: PokemonIndexState


class PokemonReindexService:
    """Build staged vectors and switch each source only after full success."""

    def __init__(
        self,
        repository: PokemonReindexRepository,
        vector_repository: VectorRepository,
        *,
        encoder_factory: Callable[[str], SentenceEncoder] = default_encoder_factory,
        batch_size: int = 64,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.repository = repository
        self.vector_repository = vector_repository
        self.encoder_factory = encoder_factory
        self.batch_size = batch_size

    def status(self, pokemon_id: int) -> PokemonIndexState:
        pokemon = self.repository.get_pokemon(pokemon_id)
        if pokemon is None:
            raise PokemonNotFoundError
        try:
            model_id = self.vector_repository.active_model().id
        except RuntimeError:
            model_id = None
        return self.repository.index_state(pokemon, model_id)

    def rebuild(self, pokemon_id: int) -> PokemonReindexSummary:
        pokemon = self.repository.get_pokemon(pokemon_id)
        if pokemon is None:
            raise PokemonNotFoundError
        try:
            model = self.vector_repository.active_model()
        except RuntimeError as exc:
            raise ReindexUnavailableError("No usable active embedding model") from exc
        if model.dimensions != 384 or not model.normalize_embeddings:
            raise ReindexUnavailableError(
                "Active embedding model must use normalized 384-dimensional vectors"
            )

        self.repository.stage_description_sources(pokemon)
        for removed in self.repository.removed_current_documents(pokemon):
            self.repository.retire_document(removed)
        documents = self.repository.matching_staged_documents(pokemon)
        pending_by_document = {
            document.id: self.repository.pending_chunks(document.id, model.id)
            for document in documents
        }
        discovered = sum(len(items) for items in pending_by_document.values())
        embedded = 0
        failed = 0

        encoder = None
        if discovered:
            try:
                encoder = self.encoder_factory(model.model_name)
            except Exception as exc:
                safe_error = self._safe_error(exc)
                for document in documents:
                    pending = pending_by_document[document.id]
                    if not pending:
                        continue
                    for candidate in pending:
                        self.vector_repository.save_failed(
                            candidate=candidate,
                            embedding_model_id=model.id,
                            error=safe_error,
                        )
                    self.repository.fail_document(document)
                    failed += len(pending)
                return self._summary(
                    pokemon_id,
                    model.id,
                    discovered,
                    embedded,
                    failed,
                )

        for document in documents:
            self.repository.retry_document(document)
            candidates = pending_by_document[document.id]
            document_failed = False
            for start in range(0, len(candidates), self.batch_size):
                batch = candidates[start : start + self.batch_size]
                try:
                    assert encoder is not None
                    encoded = list(
                        encoder.encode(
                            [candidate.content for candidate in batch],
                            batch_size=self.batch_size,
                            normalize_embeddings=True,
                            show_progress_bar=False,
                        )
                    )
                    if len(encoded) != len(batch):
                        raise ValueError(
                            "encoder returned a different number of vectors"
                        )
                    vectors = [
                        validate_embedding_vector(vector, model.dimensions)
                        for vector in encoded
                    ]
                except Exception as exc:
                    safe_error = self._safe_error(exc)
                    for candidate in batch:
                        self.vector_repository.save_failed(
                            candidate=candidate,
                            embedding_model_id=model.id,
                            error=safe_error,
                        )
                    failed += len(batch)
                    document_failed = True
                    continue

                for candidate, vector in zip(batch, vectors):
                    self.vector_repository.save_ready(
                        candidate=candidate,
                        embedding_model_id=model.id,
                        embedding=vector,
                    )
                    embedded += 1

            if (
                not document_failed
                and self.repository.document_is_ready(document.id, model.id)
            ):
                self.repository.activate_document(pokemon, document)
            else:
                self.repository.fail_document(document)

        return self._summary(
            pokemon_id,
            model.id,
            discovered,
            embedded,
            failed,
        )

    def _summary(
        self,
        pokemon_id: int,
        embedding_model_id: int,
        discovered: int,
        embedded: int,
        failed: int,
    ) -> PokemonReindexSummary:
        refreshed = self.repository.get_pokemon(pokemon_id)
        if refreshed is None:
            raise PokemonNotFoundError
        return PokemonReindexSummary(
            pokemon_id=pokemon_id,
            embedding_model_id=embedding_model_id,
            discovered=discovered,
            embedded=embedded,
            failed=failed,
            index=self.repository.index_state(refreshed, embedding_model_id),
        )

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        return f"{type(exc).__name__}: {exc}"[:2000]
