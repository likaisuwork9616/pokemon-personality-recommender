from __future__ import annotations

import unittest
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.hybrid_retrieval import FusedChunkHit, PokemonRetrievalCandidate
from app.services.recommendation import (
    HybridRecommendationEngine,
    RetrievalUnavailableError,
)
from app.services.reranking import RerankOutcome


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
    traits = tuple(f"特質{index}" for index in range(16))

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
    def type_weight_signals(_row):
        return {
            "version": "type-persona-v1",
            "combination_rule": "主屬性與副屬性原始權重相加後再正規化",
            "type_profiles": [
                {
                    "role": "主屬性",
                    "type_zh": "一般",
                    "trait_weights": {"忠誠守護者": 1.3},
                }
            ],
            "combined_top_traits": [
                {"trait": "忠誠守護者", "weight": 1.3}
            ],
        }

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


class _PersonalityRepository:
    def __init__(self, vector=None, error=None) -> None:
        self.vector = np.zeros(16) if vector is None else vector
        self.error = error
        self.calls = []

    def vector_for_text(self, text):
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.vector


class HybridRecommendationEngineTests(unittest.TestCase):
    def _engine(
        self,
        candidates,
        *,
        profile_records_loader=None,
        personality_repository=None,
        reranker=None,
    ):
        profile = _ProfileEngine()
        sessions = []
        retriever = _Retriever(candidates)
        personality = personality_repository or _PersonalityRepository()

        def session_factory():
            session = _SessionContext()
            sessions.append(session)
            return session

        engine = HybridRecommendationEngine(
            profile_engine=profile,
            session_factory=session_factory,
            embedding_model_id=9,
            retrieval_service_factory=lambda _session: retriever,
            personality_repository_factory=lambda _session: personality,
            profile_records_loader=profile_records_loader,
            reranker=reranker,
        )
        return engine, profile, sessions, retriever

    def test_applied_reranker_reorders_the_bounded_candidates(self):
        class _Reranker:
            config = SimpleNamespace(candidate_limit=3)

            @staticmethod
            def rerank(_query, candidates):
                return RerankOutcome(
                    tuple(reversed(candidates)),
                    elapsed_ms=10.0,
                    applied=True,
                    reason="applied",
                )

        engine, _profile, _sessions, _retriever = self._engine(
            [_candidate(1, 0.03), _candidate(2, 0.02), _candidate(3, 0.01)],
            reranker=_Reranker(),
        )

        results = engine.recommend("安靜守護夥伴")

        self.assertEqual([item["database_id"] for item in results], [3, 2, 1])

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
        self.assertEqual(
            engine._personality_repository_factory(None).calls,
            ["安靜守護夥伴"],
        )
        evidence = results[0]["matching_evidence"][0]
        self.assertEqual(evidence["source"], "analysis_text")
        self.assertEqual(evidence["evidence_id"], f"ev_{evidence['chunk_id'].replace('-', '')}")
        self.assertEqual(evidence["document_kind"], "analysis")
        self.assertEqual(evidence["language_code"], "mul")
        self.assertEqual(evidence["content_hash"], "a" * 64)
        self.assertEqual((evidence["dense_rank"], evidence["lexical_rank"]), (1, 1))
        self.assertTrue(all(0 <= value <= 1 for value in results[0]["scores"].values()))
        self.assertEqual(
            results[0]["type_weight_signals"]["combined_top_traits"][0],
            {"trait": "忠誠守護者", "weight": 1.3},
        )

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
        engine, _profile, _sessions, _retriever = self._engine(
            [_candidate(1, 0.03), _candidate(2, 0.02), _candidate(3, 0.01)],
            personality_repository=_PersonalityRepository(
                error=RuntimeError("database details must stay internal")
            ),
        )
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

    def test_personality_catalog_refresh_rebuilds_profile_vectors_atomically(self):
        engine, original, _sessions, _retriever = self._engine([])
        traits = tuple(f"新特質{index}" for index in range(16))
        catalog = SimpleNamespace(
            trait_names=traits,
            synonyms_by_trait={trait: (f"詞{index}",) for index, trait in enumerate(traits)},
        )

        count = engine.refresh_personality_catalog(catalog)

        self.assertEqual(count, 16)
        self.assertIsNot(engine.profile_engine, original)
        self.assertEqual(engine.profile_engine.traits, traits)
        self.assertEqual(engine.profile_engine.persona_keywords[traits[3]], ["詞3"])
        self.assertEqual(engine.profile_engine.persona_vectors.shape, (3, 16))

    def test_failed_personality_refresh_preserves_snapshot_and_self_heals_readiness(self):
        traits = tuple(f"恢復特質{index}" for index in range(16))

        class VersionedPersonality(_PersonalityRepository):
            @staticmethod
            def revision():
                return 2

            @staticmethod
            def catalog():
                return SimpleNamespace(
                    trait_names=traits,
                    synonyms_by_trait={
                        trait: (f"詞{index}",)
                        for index, trait in enumerate(traits)
                    },
                )

        engine, original, _sessions, _retriever = self._engine(
            [_candidate(1, 0.03), _candidate(2, 0.02), _candidate(3, 0.01)],
            personality_repository=VersionedPersonality(),
        )
        engine._personality_revision = 1
        original_state = engine._profile_state
        incomplete_catalog = SimpleNamespace(
            trait_names=traits,
            synonyms_by_trait={trait: ("詞",) for trait in traits[:-1]},
        )

        with self.assertRaises(KeyError):
            engine.refresh_personality_catalog(incomplete_catalog, revision=2)

        self.assertIs(engine.profile_engine, original)
        self.assertIs(engine._profile_state, original_state)
        self.assertEqual(engine._personality_revision, 1)
        self.assertFalse(engine.personality_refresh_healthy)

        with TestClient(create_app(lambda: engine)) as client:
            degraded = client.get("/health/ready")
            recovered_request = client.post(
                "/api/v1/recommendations",
                json={"text": "安靜守護夥伴"},
            )
            recovered = client.get("/health/ready")

        self.assertEqual(degraded.status_code, 503)
        self.assertEqual(degraded.json()["reason"], "personality_refresh_pending")
        self.assertEqual(recovered_request.status_code, 200)
        self.assertEqual(recovered.json(), {"status": "ready"})
        self.assertTrue(engine.personality_refresh_healthy)
        self.assertEqual(engine._personality_revision, 2)
        self.assertEqual(engine.profile_engine.traits, traits)

    def test_changed_database_revision_self_refreshes_before_scoring(self):
        traits = tuple(f"跨程序特質{index}" for index in range(16))

        class VersionedPersonality(_PersonalityRepository):
            @staticmethod
            def revision():
                return 2

            @staticmethod
            def catalog():
                return SimpleNamespace(
                    trait_names=traits,
                    synonyms_by_trait={trait: (f"詞{index}",) for index, trait in enumerate(traits)},
                )

        engine, _profile, _sessions, _retriever = self._engine(
            [_candidate(1, 0.03), _candidate(2, 0.02), _candidate(3, 0.01)],
            personality_repository=VersionedPersonality(),
        )
        engine._personality_revision = 1

        engine.recommend("安靜守護夥伴")

        self.assertEqual(engine._personality_revision, 2)
        self.assertEqual(engine.profile_engine.traits, traits)


if __name__ == "__main__":
    unittest.main()
