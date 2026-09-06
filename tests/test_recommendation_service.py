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

    def _validate_columns(self):
        if "_database_id" not in self.df:
            raise ValueError("missing database identity")

    def build_persona_vectors(self):
        return np.zeros((len(self.df), 16))

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
    def _engine(self, candidates, *, profile_records_loader=None):
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
            profile_records_loader=profile_records_loader,
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
        evidence = results[0]["matching_evidence"][0]
        self.assertEqual(evidence["source"], "analysis_text")
        self.assertEqual(evidence["evidence_id"], f"ev_{evidence['chunk_id'].replace('-', '')}")
        self.assertEqual(evidence["document_kind"], "analysis")
        self.assertEqual(evidence["language_code"], "mul")
        self.assertEqual(evidence["content_hash"], "a" * 64)
        self.assertEqual((evidence["dense_rank"], evidence["lexical_rank"]), (1, 1))
        self.assertTrue(all(0 <= value <= 1 for value in results[0]["scores"].values()))

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

    def test_personality_error_does_not_include_the_raw_query(self):
        engine, profile, _sessions, _retriever = self._engine(
            [_candidate(1, 0.03), _candidate(2, 0.02), _candidate(3, 0.01)]
        )

        def fail(text):
            raise RuntimeError(f"failed while processing {text}")

        profile.text_to_persona_vector = fail
        with self.assertRaisesRegex(
            RetrievalUnavailableError,
            "personality scoring is temporarily unavailable",
        ) as caught:
            engine.recommend("安靜守護夥伴")

        self.assertNotIn("安靜守護夥伴", str(caught.exception))

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

    def test_newly_indexed_id_self_refreshes_profile_snapshot(self):
        records = _ProfileEngine().df.to_dict(orient="records")
        records[-1] = {
            **records[-1],
            "_database_id": 4,
            "pokedex_number": 4,
            "name_zh": "新加入的寶可夢",
        }
        loader_calls = []

        def load_records():
            loader_calls.append(True)
            return records

        engine, _profile, _sessions, _retriever = self._engine(
            [_candidate(1, 0.03), _candidate(2, 0.02), _candidate(4, 0.01)],
            profile_records_loader=load_records,
        )

        results = engine.recommend("安靜守護夥伴")

        self.assertEqual([item["database_id"] for item in results], [1, 2, 4])
        self.assertEqual(results[-1]["name"], "新加入的寶可夢")
        self.assertEqual(len(loader_calls), 1)


if __name__ == "__main__":
    unittest.main()
