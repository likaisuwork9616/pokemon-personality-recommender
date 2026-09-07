from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pandas as pd
from sqlalchemy.dialects import postgresql

from app.db import Base
from app.repositories.vector import (
    EmbeddingCandidate,
    VectorRepository,
    VectorSearchConfig,
)
from app.services.embedding import EmbeddingConfig, EmbeddingService
from app.services.personality_profile import PokemonPersonalityProfile


ROOT = Path(__file__).resolve().parents[1]


class _FakeRepository:
    def __init__(self, candidates: list[EmbeddingCandidate]) -> None:
        self.candidates = candidates
        self.ready: list[tuple[EmbeddingCandidate, list[float]]] = []
        self.failed: list[tuple[EmbeddingCandidate, str]] = []

    def ensure_model(self, **_kwargs):
        return SimpleNamespace(id=7)

    def pending_chunks(self, _model_id: int):
        ready_ids = {candidate.chunk_id for candidate, _vector in self.ready}
        return [item for item in self.candidates if item.chunk_id not in ready_ids]

    def save_ready(self, *, candidate, embedding_model_id, embedding):
        self.assert_model_id(embedding_model_id)
        self.ready.append((candidate, list(embedding)))

    def save_failed(self, *, candidate, embedding_model_id, error):
        self.assert_model_id(embedding_model_id)
        self.failed.append((candidate, error))

    @staticmethod
    def assert_model_id(model_id: int) -> None:
        if model_id != 7:
            raise AssertionError(f"unexpected model id: {model_id}")


class _FakeEncoder:
    def __init__(self, dimensions: int = 384, *, raises: bool = False) -> None:
        self.dimensions = dimensions
        self.raises = raises
        self.calls = 0

    def encode(self, sentences, **_kwargs):
        self.calls += 1
        if self.raises:
            raise RuntimeError("synthetic encoder failure")
        return [[2.0, *([0.0] * (self.dimensions - 1))] for _ in sentences]


def _candidate(content: str = "可追蹤的寶可夢證據") -> EmbeddingCandidate:
    return EmbeddingCandidate(uuid4(), content, "a" * 64)


class EmbeddingServiceTests(unittest.TestCase):
    def test_success_is_normalized_and_second_run_is_idempotent(self):
        repository = _FakeRepository([_candidate(), _candidate("另一段證據")])
        encoder = _FakeEncoder()
        service = EmbeddingService(repository, encoder_factory=lambda _name: encoder)

        first = service.rebuild()
        second = service.rebuild()

        self.assertEqual((first.discovered, first.embedded, first.failed), (2, 2, 0))
        self.assertEqual((second.discovered, second.embedded), (0, 0))
        self.assertEqual(encoder.calls, 1)
        self.assertTrue(all(vector[0] == 1.0 for _candidate, vector in repository.ready))

    def test_encoder_failure_persists_failed_status_without_text(self):
        repository = _FakeRepository([_candidate()])
        service = EmbeddingService(
            repository,
            encoder_factory=lambda _name: _FakeEncoder(raises=True),
        )

        summary = service.rebuild()

        self.assertEqual((summary.embedded, summary.failed), (0, 1))
        self.assertIn("RuntimeError", repository.failed[0][1])
        self.assertNotIn(repository.failed[0][0].content, repository.failed[0][1])

    def test_invalid_dimensions_mark_the_complete_batch_failed(self):
        repository = _FakeRepository([_candidate(), _candidate()])
        summary = EmbeddingService(
            repository,
            encoder_factory=lambda _name: _FakeEncoder(dimensions=3),
        ).rebuild()

        self.assertEqual(summary.failed, 2)
        self.assertEqual(repository.ready, [])

    def test_no_work_does_not_load_sentence_transformer(self):
        repository = _FakeRepository([])

        summary = EmbeddingService(
            repository,
            encoder_factory=lambda _name: self.fail("encoder should stay lazy"),
        ).rebuild()

        self.assertEqual(summary.discovered, 0)

    def test_config_rejects_non_mvp_dimensions(self):
        with self.assertRaisesRegex(ValueError, "384"):
            EmbeddingConfig(dimensions=3)

    def test_database_profile_does_not_build_an_in_memory_corpus_embedding(self):
        row = {
            "pokedex_number": 1,
            "name_zh": "妙蛙種子",
            "name_en": "Bulbasaur",
            "type_zh": "草, 毒",
            "category_zh": "種子寶可夢",
            "description_zh": "重視夥伴",
            "analysis_text": "沉穩",
            "image_url": "https://example.test/1.png",
        }
        with (
            patch.object(
                PokemonPersonalityProfile,
                "_load_sentence_model",
                return_value=object(),
            ),
        ):
            profile = PokemonPersonalityProfile(
                dataframe=pd.DataFrame([row]),
                personality_traits=tuple(f"特質{index}" for index in range(16)),
                persona_keywords={
                    f"特質{index}": (f"關鍵字{index}",)
                    for index in range(16)
                },
            )

        self.assertEqual(profile.persona_vectors.shape, (1, 16))
        self.assertFalse(hasattr(profile, "pokemon_embeddings"))


class PgvectorSchemaTests(unittest.TestCase):
    def test_models_use_fixed_vector_and_hash_model_primary_key(self):
        models = Base.metadata.tables["embedding_models"]
        embeddings = Base.metadata.tables["pokemon_chunk_embeddings"]

        self.assertEqual(str(embeddings.c.embedding.type), "VECTOR(384)")
        self.assertTrue(embeddings.c.embedding.nullable)
        self.assertEqual(
            tuple(column.name for column in embeddings.primary_key.columns),
            ("chunk_id", "embedding_model_id"),
        )
        self.assertEqual(models.c.dimensions.server_default.arg.text, "384")

    def test_embedding_migrations_progress_from_exact_to_hnsw(self):
        source = (
            ROOT / "alembic" / "versions" / "20260906_0003_chunk_embeddings.py"
        ).read_text(encoding="utf-8")
        hnsw_source = (
            ROOT / "alembic" / "versions" / "20260907_0005_hnsw_index.py"
        ).read_text(encoding="utf-8")

        self.assertIn("Vector(384)", source)
        self.assertIn('down_revision: str | None = "20260906_0002"', source)
        self.assertNotIn("hnsw", source.casefold())
        self.assertIn('down_revision: str | None = "20260907_0004"', hnsw_source)
        self.assertIn('postgresql_using="hnsw"', hnsw_source)
        self.assertIn('"embedding": "vector_cosine_ops"', hnsw_source)

    def test_hnsw_runtime_configuration_is_validated(self):
        self.assertEqual(VectorSearchConfig().mode, "hnsw")
        with self.assertRaisesRegex(ValueError, "exact or hnsw"):
            VectorSearchConfig(mode="invalid")
        with self.assertRaisesRegex(ValueError, "between 1 and 1000"):
            VectorSearchConfig(ef_search=0)

    def test_pending_query_enforces_all_visibility_guards(self):
        class CaptureSession:
            statement = None

            def execute(self, statement):
                self.statement = statement
                return []

        session = CaptureSession()
        VectorRepository(session).pending_chunks(1)
        sql = str(
            session.statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertIn("pokemon.is_active IS true", sql)
        self.assertIn("pokemon_knowledge_documents.is_current IS true", sql)
        self.assertIn("pokemon_knowledge_chunks.is_current IS true", sql)
        self.assertIn("pokemon_chunk_embeddings.content_hash IS DISTINCT FROM", sql)

    def test_exact_search_rejects_invalid_vectors_before_database_use(self):
        repository = VectorRepository(object())
        with self.assertRaisesRegex(ValueError, "384 finite"):
            repository.exact_search(
                query_vector=[0.0, 1.0],
                embedding_model_id=1,
            )


if __name__ == "__main__":
    unittest.main()
