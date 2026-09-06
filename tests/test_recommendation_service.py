from __future__ import annotations

import unittest
from uuid import uuid4

import numpy as np
import pandas as pd

from app.services.hybrid_retrieval import FusedChunkHit, PokemonRetrievalCandidate
from app.services.recommendation import (
    HybridRecommendationEngine,
    RetrievalUnavailableError,
)


class _Encoder:
    def __init__(self) -> None:
        self.calls = 0

    def encode(self, text, **kwargs):
        self.calls += 1
        if text != "安靜守護夥伴" or kwargs != {"normalize_embeddings": True}:
            raise AssertionError("unexpected query encoder input")
        return np.array([1.0, *([0.0] * 383)])


class _ProfileEngine:
    id_col = "pokedex_number"
    name_col = "name_zh"
    name_en_col = "name_en"
    type_col = "type_zh"
    type_1_col = "type_1"
    type_2_col = "type_2"
    cat_col = "category_zh"
    genus_col = "genus"
    desc_col = "description_zh"
    flavor_en_col = "flavor_text_en"
    analysis_col = "analysis_text"
    img_col = "image_url"
    sprite_col = "sprite_url"

    def __init__(self) -> None:
        self.st_model = _Encoder()
        self.df = pd.DataFrame(
            [
                {
                    "_database_id": database_id,
                    "pokedex_number": database_id,
                    "name_zh": f"寶可夢{database_id}",
                    "name_en": f"Pokemon {database_id}",
                    "type_zh": "一般",
                    "type_1": "Normal",
                    "type_2": "Unknown",
                    "category_zh": "測試",
                    "genus": "Test",
                    "description_zh": "安靜守護夥伴",
                    "flavor_text_en": "Quiet and loyal",
                    "analysis_text": "忠誠",
                    "image_url": "",
                    "sprite_url": "",
                }
                for database_id in (1, 2, 3)
            ]
        )
        self.persona_vectors = np.zeros((3, 16))

    @staticmethod
    def text_to_persona_vector(_text):
        return np.zeros(16)

    @staticmethod
    def get_top_traits(_vector):
        return ["忠誠守護者"]

    @staticmethod
    def safe_get(row, column, default=""):
        return row.get(column, default)

    @staticmethod
    def explain(_text, pokemon):
        return f"推薦 {pokemon['name']}"


def _candidate(pokemon_id: int, score: float) -> PokemonRetrievalCandidate:
    document_id = uuid4()
    chunk_id = uuid4()
    evidence = FusedChunkHit(
        pokemon_id=pokemon_id,
        document_id=document_id,
        chunk_id=chunk_id,
        source_key="analysis_text",
        document_kind="analysis",
        language_code="mul",
        content=f"寶可夢 {pokemon_id} 的可追蹤證據",
        content_hash="a" * 64,
        dense_rank=pokemon_id,
        dense_score=0.8,
        lexical_rank=pokemon_id,
        lexical_score=0.5,
        rrf_score=score,
    )
    return PokemonRetrievalCandidate(
        pokemon_id=pokemon_id,
        retrieval_score=score,
        best_chunk_score=score,
        best_branch_rank=pokemon_id,
        evidence=(evidence,),
    )


class _SessionContext:
    def __init__(self) -> None:
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True


class _Retriever:
    def __init__(self, candidates) -> None:
        self.candidates = candidates
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return self.candidates


class HybridRecommendationEngineTests(unittest.TestCase):
    def _engine(self, candidates):
        profile = _ProfileEngine()
        sessions = []
        retriever = _Retriever(candidates)

        def session_factory():
            session = _SessionContext()
            sessions.append(session)
            return session

        engine = HybridRecommendationEngine(
            profile_engine=profile,
            session_factory=session_factory,
            embedding_model_id=9,
            retrieval_service_factory=lambda _session: retriever,
        )
        return engine, profile, sessions, retriever

    def test_query_is_encoded_once_and_returns_stable_top_three(self):
        candidates = [_candidate(2, 0.02), _candidate(1, 0.03), _candidate(3, 0.01)]
        engine, profile, sessions, retriever = self._engine(candidates)

        results = engine.recommend("安靜守護夥伴")

        self.assertEqual([item["database_id"] for item in results], [1, 2, 3])
        self.assertEqual([item["rank"] for item in results], [1, 2, 3])
        self.assertEqual(profile.st_model.calls, 1)
        self.assertTrue(sessions[0].closed)
        self.assertEqual(retriever.calls[0]["embedding_model_id"], 9)
        self.assertEqual(len(retriever.calls[0]["query_vector"]), 384)
        self.assertEqual(results[0]["matching_evidence"][0]["source"], "analysis_text")

    def test_incomplete_unique_candidates_are_a_service_error(self):
        engine, _profile, sessions, _retriever = self._engine(
            [_candidate(1, 0.03), _candidate(2, 0.02)]
        )

        with self.assertRaisesRegex(RetrievalUnavailableError, "only 2"):
            engine.recommend("安靜守護夥伴")

        self.assertTrue(sessions[0].closed)

    def test_validation_happens_before_query_encoding_or_database_use(self):
        engine, profile, sessions, _retriever = self._engine([])

        with self.assertRaises(ValueError):
            engine.recommend("   ")

        self.assertEqual(profile.st_model.calls, 0)
        self.assertEqual(sessions, [])

    def test_retrieval_error_is_sanitized_and_session_is_closed(self):
        engine, _profile, sessions, retriever = self._engine([])

        def fail(**_kwargs):
            raise RuntimeError("database details must stay internal")

        retriever.retrieve = fail
        with self.assertRaisesRegex(
            RetrievalUnavailableError,
            "hybrid retrieval is temporarily unavailable",
        ) as caught:
            engine.recommend("安靜守護夥伴")

        self.assertNotIn("database details", str(caught.exception))
        self.assertTrue(sessions[0].closed)

    def test_duplicate_candidates_are_rejected_at_engine_boundary(self):
        duplicate = _candidate(1, 0.03)
        engine, _profile, _sessions, _retriever = self._engine(
            [duplicate, duplicate, _candidate(2, 0.02)]
        )

        with self.assertRaisesRegex(RetrievalUnavailableError, "duplicate"):
            engine.recommend("安靜守護夥伴")

    def test_equal_scores_use_catalog_identity_not_input_order(self):
        same_score = 0.02
        engine, _profile, _sessions, _retriever = self._engine(
            [
                _candidate(3, same_score),
                _candidate(1, same_score),
                _candidate(2, same_score),
            ]
        )

        results = engine.recommend("安靜守護夥伴")

        self.assertEqual([item["database_id"] for item in results], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
