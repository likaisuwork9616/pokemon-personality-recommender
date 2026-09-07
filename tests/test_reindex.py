from __future__ import annotations

import unittest
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.db.models import (
    Pokemon,
    PokemonDescription,
    PokemonKnowledgeChunk,
    PokemonKnowledgeDocument,
)
from app.repositories.reindex import PokemonIndexState, PokemonReindexRepository
from app.repositories.vector import EmbeddingCandidate
from app.services.knowledge import content_hash
from app.services.reindex import PokemonReindexService


class _StagingSession:
    def __init__(self) -> None:
        self.flushes = 0

    def flush(self) -> None:
        self.flushes += 1


class ReindexStagingTests(unittest.TestCase):
    def test_changed_description_creates_non_serving_version(self):
        old_content = "舊的性格敘述"
        new_content = "新的性格敘述，重視合作與可靠。"
        pokemon = Pokemon(
            id=1,
            pokedex_number=1,
            form_key="default",
            name_zh="妙蛙種子",
            name_en="Bulbasaur",
            generation=1,
        )
        description = PokemonDescription(
            id=10,
            pokemon_id=1,
            language_code="mul",
            description_kind="analysis",
            source_key="csv:analysis_text",
            content=new_content,
            content_hash=content_hash(new_content),
            is_primary=True,
        )
        old_document = PokemonKnowledgeDocument(
            id=uuid4(),
            pokemon_id=1,
            source_key="analysis_text",
            document_kind="analysis_text",
            language_code="mul",
            content=old_content,
            content_hash=content_hash(old_content),
            version=1,
            is_current=True,
            status="ready",
        )
        old_document.chunks = [
            PokemonKnowledgeChunk(
                id=uuid4(),
                chunk_index=0,
                content=old_content,
                lexical_text=old_content,
                content_hash=content_hash(old_content),
                char_count=len(old_content),
                token_count=1,
                is_current=True,
                status="ready",
            )
        ]
        pokemon.descriptions = [description]
        pokemon.knowledge_documents = [old_document]
        session = _StagingSession()

        staged = PokemonReindexRepository(session).stage_description_sources(
            pokemon,
            {"analysis_text"},
        )

        self.assertEqual(staged, 1)
        replacement = max(pokemon.knowledge_documents, key=lambda item: item.version)
        self.assertEqual(replacement.version, 2)
        self.assertEqual(replacement.content, new_content)
        self.assertFalse(replacement.is_current)
        self.assertEqual(replacement.status, "stale")
        self.assertTrue(replacement.chunks)
        self.assertTrue(all(not chunk.is_current for chunk in replacement.chunks))
        self.assertTrue(old_document.is_current)
        self.assertEqual(old_document.status, "ready")

        second = PokemonReindexRepository(session).stage_description_sources(
            pokemon,
            {"analysis_text"},
        )
        self.assertEqual(second, 0)
        self.assertEqual(len(pokemon.knowledge_documents), 2)


class _FakeVectorRepository:
    def __init__(self, candidates: list[EmbeddingCandidate]) -> None:
        self.model = SimpleNamespace(
            id=7,
            model_name="fake-multilingual-model",
            dimensions=384,
            normalize_embeddings=True,
        )
        self.candidates = candidates
        self.ready: set[UUID] = set()
        self.failed: set[UUID] = set()

    def active_model(self):
        return self.model

    def save_ready(self, *, candidate, embedding_model_id, embedding):
        if embedding_model_id != self.model.id or len(embedding) != 384:
            raise AssertionError("invalid ready vector")
        self.ready.add(candidate.chunk_id)
        self.failed.discard(candidate.chunk_id)

    def save_failed(self, *, candidate, embedding_model_id, error):
        if embedding_model_id != self.model.id or candidate.content in error:
            raise AssertionError("unsafe failure state")
        self.failed.add(candidate.chunk_id)
        self.ready.discard(candidate.chunk_id)


class _FakeReindexRepository:
    def __init__(self, vectors: _FakeVectorRepository) -> None:
        self.vectors = vectors
        self.pokemon = SimpleNamespace(id=25)
        self.old_current = True
        self.document = SimpleNamespace(id=uuid4(), status="stale")
        self.activated = False
        self.retired = []

    def get_pokemon(self, pokemon_id):
        return self.pokemon if pokemon_id == self.pokemon.id else None

    @staticmethod
    def stage_description_sources(_pokemon):
        return 0

    @staticmethod
    def removed_current_documents(_pokemon):
        return []

    def matching_staged_documents(self, _pokemon):
        return [self.document]

    def pending_chunks(self, _document_id, _model_id):
        return [
            item
            for item in self.vectors.candidates
            if item.chunk_id not in self.vectors.ready
        ]

    def retry_document(self, document):
        document.status = "stale"

    def fail_document(self, document):
        document.status = "failed"

    def document_is_ready(self, _document_id, _model_id):
        return len(self.vectors.ready) == len(self.vectors.candidates)

    def activate_document(self, _pokemon, document):
        if not self.document_is_ready(document.id, 7):
            raise AssertionError("replacement activated before all vectors were ready")
        self.old_current = False
        self.activated = True
        document.status = "ready"

    def retire_document(self, document):
        self.retired.append(document)

    def index_state(self, _pokemon, _model_id):
        return PokemonIndexState(
            pokemon_id=self.pokemon.id,
            status="ready" if self.activated else self.document.status,
            sources=(),
        )


class _Encoder:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def encode(self, sentences, **_kwargs):
        if self.fail:
            raise RuntimeError("synthetic encoder failure")
        return [[1.0, *([0.0] * 383)] for _sentence in sentences]


class ReindexServiceTests(unittest.TestCase):
    def candidates(self):
        return [
            EmbeddingCandidate(uuid4(), "第一段內容", "a" * 64),
            EmbeddingCandidate(uuid4(), "第二段內容", "b" * 64),
        ]

    def test_success_embeds_every_chunk_before_atomic_switch(self):
        vectors = _FakeVectorRepository(self.candidates())
        repository = _FakeReindexRepository(vectors)
        service = PokemonReindexService(
            repository,
            vectors,
            encoder_factory=lambda _name: _Encoder(),
        )

        summary = service.rebuild(25)

        self.assertEqual((summary.discovered, summary.embedded, summary.failed), (2, 2, 0))
        self.assertTrue(repository.activated)
        self.assertFalse(repository.old_current)
        self.assertEqual(summary.index.status, "ready")

    def test_progress_callback_reports_discovery_and_completed_chunks(self):
        vectors = _FakeVectorRepository(self.candidates())
        repository = _FakeReindexRepository(vectors)
        updates = []
        service = PokemonReindexService(repository, vectors, encoder_factory=lambda _name: _Encoder(), batch_size=1)

        service.rebuild(25, progress_callback=lambda *values: updates.append(values))

        self.assertEqual(updates[0][:2], (0, 2))
        self.assertEqual(updates[-1][:4], (2, 2, 2, 0))

    def test_failure_preserves_old_index_and_retry_can_activate(self):
        vectors = _FakeVectorRepository(self.candidates())
        repository = _FakeReindexRepository(vectors)
        failed = PokemonReindexService(
            repository,
            vectors,
            encoder_factory=lambda _name: _Encoder(fail=True),
        ).rebuild(25)

        self.assertEqual((failed.embedded, failed.failed), (0, 2))
        self.assertTrue(repository.old_current)
        self.assertFalse(repository.activated)
        self.assertEqual(repository.document.status, "failed")

        retried = PokemonReindexService(
            repository,
            vectors,
            encoder_factory=lambda _name: _Encoder(),
        ).rebuild(25)
        self.assertEqual((retried.embedded, retried.failed), (2, 0))
        self.assertTrue(repository.activated)
        self.assertFalse(repository.old_current)


if __name__ == "__main__":
    unittest.main()
