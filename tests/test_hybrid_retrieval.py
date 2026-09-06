from __future__ import annotations

import unittest
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.repositories.retrieval import LexicalSearchHit, RetrievalRepository
from app.repositories.vector import VectorRepository, VectorSearchHit
from app.services.hybrid_retrieval import (
    HybridRetrievalService,
    RRF_K,
    tokenize_lexical_query,
)


def _uuid(number: int) -> UUID:
    return UUID(int=number)


def _dense(rank: int, pokemon_id: int, chunk_number: int) -> VectorSearchHit:
    return VectorSearchHit(
        rank=rank,
        pokemon_id=pokemon_id,
        document_id=_uuid(1000 + chunk_number),
        chunk_id=_uuid(chunk_number),
        source_key="description_zh",
        document_kind="description_zh",
        language_code="zh-Hant",
        content=f"證據 {chunk_number}",
        content_hash=f"{chunk_number:064x}",
        semantic_score=0.9,
    )


def _lexical(rank: int, pokemon_id: int, chunk_number: int) -> LexicalSearchHit:
    return LexicalSearchHit(
        rank=rank,
        pokemon_id=pokemon_id,
        document_id=_uuid(1000 + chunk_number),
        chunk_id=_uuid(chunk_number),
        source_key="description_zh",
        document_kind="description_zh",
        language_code="zh-Hant",
        content=f"證據 {chunk_number}",
        content_hash=f"{chunk_number:064x}",
        lexical_score=0.8,
    )


class _DenseRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def exact_search(self, **kwargs):
        self.calls.append(kwargs)
        return self.hits


class _LexicalRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def lexical_search(self, **kwargs):
        self.calls.append(kwargs)
        return self.hits


class TokenizationTests(unittest.TestCase):
    def test_tokens_drop_punctuation_dedupe_casefold_and_cap_at_32(self):
        text = "冷靜 冷靜 !!! calm CALM " + " ".join(f"特質{n}" for n in range(40))

        tokens = tokenize_lexical_query(text)

        self.assertEqual(tokens[:2], ("冷靜", "calm"))
        self.assertEqual(len(tokens), 32)
        self.assertFalse(any(token == "!" for token in tokens))

    def test_punctuation_only_query_has_no_tokens(self):
        self.assertEqual(tokenize_lexical_query("!!! ，。？"), ())


class RetrievalSqlTests(unittest.TestCase):
    def test_lexical_sql_is_parameterized_or_fts_with_visibility_guards(self):
        class CaptureSession:
            statement = None

            def execute(self, statement):
                self.statement = statement
                return []

        session = CaptureSession()
        malicious = "') | !danger:("
        RetrievalRepository(session).lexical_search(
            tokens=("冷靜", malicious),
            limit=50,
        )
        compiled = session.statement.compile(dialect=postgresql.dialect())
        sql = str(compiled)

        self.assertIn("plainto_tsquery", sql)
        self.assertIn(" || ", sql)
        self.assertIn(" @@ ", sql)
        self.assertIn("pokemon.is_active IS true", sql)
        self.assertIn("pokemon_knowledge_documents.is_current IS true", sql)
        self.assertNotIn(malicious, sql)
        self.assertIn(malicious, compiled.params.values())

    def test_dense_sql_requires_the_selected_model_to_be_active(self):
        class CaptureSession:
            statement = None

            def execute(self, statement):
                self.statement = statement
                return []

        session = CaptureSession()
        VectorRepository(session).exact_search(
            query_vector=[1.0, *([0.0] * 383)],
            embedding_model_id=7,
            limit=50,
        )
        sql = str(session.statement.compile(dialect=postgresql.dialect()))

        self.assertIn("JOIN embedding_models", sql)
        self.assertIn("embedding_models.is_active IS true", sql)
        self.assertIn("pokemon_chunk_embeddings.content_hash =", sql)
        self.assertIn("pokemon.is_active IS true", sql)

    def test_active_model_queries_at_most_two_active_rows(self):
        class CaptureSession:
            statement = None

            def scalars(self, statement):
                self.statement = statement
                return [SimpleNamespace(id=7, dimensions=384)]

        session = CaptureSession()

        model = VectorRepository(session).active_model()
        sql = str(session.statement.compile(dialect=postgresql.dialect()))

        self.assertEqual(model.id, 7)
        self.assertIn("embedding_models.is_active IS true", sql)
        self.assertEqual(session.statement._limit_clause.value, 2)

    def test_active_model_reports_missing_and_duplicate_configuration(self):
        class ScalarSession:
            def __init__(self, models):
                self.models = models

            def scalars(self, _statement):
                return self.models

        with self.assertRaisesRegex(RuntimeError, "No active"):
            VectorRepository(ScalarSession([])).active_model()
        duplicate = [
            SimpleNamespace(id=1, dimensions=384),
            SimpleNamespace(id=2, dimensions=384),
        ]
        with self.assertRaisesRegex(RuntimeError, "Multiple active"):
            VectorRepository(ScalarSession(duplicate)).active_model()

    def test_ready_pokemon_count_uses_the_complete_visibility_guard(self):
        class CaptureSession:
            statement = None

            def scalar(self, statement):
                self.statement = statement
                return 3

        session = CaptureSession()

        count = VectorRepository(session).ready_pokemon_count(7)
        sql = str(session.statement.compile(dialect=postgresql.dialect()))

        self.assertEqual(count, 3)
        self.assertIn("count(distinct(pokemon.id))", sql)
        self.assertIn("embedding_models.is_active IS true", sql)
        self.assertIn("pokemon_chunk_embeddings.content_hash =", sql)
        self.assertIn("pokemon_knowledge_documents.is_current IS true", sql)
        self.assertIn("pokemon_knowledge_chunks.is_current IS true", sql)
        self.assertIn("pokemon.is_active IS true", sql)


class HybridFusionTests(unittest.TestCase):
    def test_same_chunk_combines_both_rrf_contributions(self):
        service = HybridRetrievalService(
            _DenseRetriever([_dense(1, 10, 1)]),
            _LexicalRetriever([_lexical(1, 10, 1)]),
        )

        results = service.retrieve(
            query_text="冷靜",
            query_vector=[1.0, *([0.0] * 383)],
            embedding_model_id=7,
        )

        evidence = results[0].evidence[0]
        self.assertAlmostEqual(evidence.rrf_score, 2 / (RRF_K + 1))
        self.assertEqual((evidence.dense_rank, evidence.lexical_rank), (1, 1))

    def test_duplicate_chunk_within_a_branch_keeps_its_smallest_rank(self):
        service = HybridRetrievalService(
            _DenseRetriever([_dense(1, 10, 1), _dense(7, 10, 1)]),
            _LexicalRetriever([_lexical(5, 10, 1), _lexical(2, 10, 1)]),
        )

        results = service.retrieve(
            query_text="冷靜",
            query_vector=[1.0, *([0.0] * 383)],
            embedding_model_id=7,
        )

        evidence = results[0].evidence[0]
        self.assertEqual((evidence.dense_rank, evidence.lexical_rank), (1, 2))
        self.assertAlmostEqual(
            evidence.rrf_score,
            1 / (RRF_K + 1) + 1 / (RRF_K + 2),
        )

    def test_only_top_three_chunks_influence_each_pokemon(self):
        dense = [_dense(rank, 20, rank) for rank in range(1, 5)]
        service = HybridRetrievalService(_DenseRetriever(dense), _LexicalRetriever([]))

        results = service.retrieve(
            query_text="",
            query_vector=[1.0, *([0.0] * 383)],
            embedding_model_id=7,
        )

        candidate = results[0]
        scores = [1 / (RRF_K + rank) for rank in range(1, 4)]
        expected = 0.75 * scores[0] + 0.25 * (sum(scores) / 3)
        self.assertEqual(len(candidate.evidence), 3)
        self.assertAlmostEqual(candidate.retrieval_score, expected)
        self.assertNotIn(_uuid(4), {item.chunk_id for item in candidate.evidence})

    def test_stable_ties_use_pokemon_id(self):
        service = HybridRetrievalService(
            _DenseRetriever([_dense(1, 2, 2)]),
            _LexicalRetriever([_lexical(1, 1, 1)]),
        )

        results = service.retrieve(
            query_text="守護",
            query_vector=[1.0, *([0.0] * 383)],
            embedding_model_id=7,
        )

        self.assertEqual([item.pokemon_id for item in results], [1, 2])

    def test_candidate_tie_prefers_the_best_branch_rank_before_pokemon_id(self):
        service = HybridRetrievalService(_DenseRetriever([]), _LexicalRetriever([]))
        higher_id_better_rank = service._fuse_chunks(
            [_dense(1, 9, 9)],
            [],
        )[0]
        lower_id_worse_rank = service._fuse_chunks(
            [_dense(2, 1, 1)],
            [],
        )[0]
        # Force an exact score tie to exercise only the deterministic tie-break.
        higher_id_better_rank = higher_id_better_rank.__class__(
            **{
                **higher_id_better_rank.__dict__,
                "rrf_score": lower_id_worse_rank.rrf_score,
            }
        )

        results = service._aggregate_pokemon(
            [lower_id_worse_rank, higher_id_better_rank]
        )

        self.assertEqual([item.pokemon_id for item in results], [9, 1])

    def test_branch_limit_is_50_and_empty_tokens_skip_lexical_database_call(self):
        dense = _DenseRetriever([])
        lexical = _LexicalRetriever([])
        service = HybridRetrievalService(dense, lexical)

        service.retrieve(
            query_text="!!!",
            query_vector=[1.0, *([0.0] * 383)],
            embedding_model_id=7,
        )

        self.assertEqual(dense.calls[0]["limit"], 50)
        self.assertEqual(lexical.calls, [])

    def test_mismatched_branch_lineage_is_rejected(self):
        dense = _dense(1, 1, 1)
        lexical = _lexical(1, 2, 1)
        with self.assertRaisesRegex(ValueError, "lineage"):
            HybridRetrievalService(
                _DenseRetriever([dense]),
                _LexicalRetriever([lexical]),
            ).retrieve(
                query_text="冷靜",
                query_vector=[1.0, *([0.0] * 383)],
                embedding_model_id=7,
            )


if __name__ == "__main__":
    unittest.main()
