from __future__ import annotations

from dataclasses import replace
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pandas as pd

from app.repositories.mbti_profiles import IndexedBehaviorProfile
from app.services.hybrid_retrieval import FusedChunkHit, PokemonRetrievalCandidate
from app.services.mbti_scoring import MbtiScorer
from app.services.personality_profile import PokemonPersonalityProfile
from app.services.recommendation import HybridRecommendationEngine, RetrievalUnavailableError


def _catalog():
    codes = ("ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP",
             "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ")
    profiles = tuple(SimpleNamespace(
        code=code, name_zh=f"參考{index}", summary=f"詳細行為摘要{index}",
        information_style="理解資訊", decision_style="決策方式",
        interaction_style="互動方式", action_style="行動方式", strengths=("合作",),
        matching_text=f"詳細行為摘要{index} 理解資訊 決策方式 互動方式 行動方式",
        weighted_terms=(SimpleNamespace(term="安靜" if index == 0 else f"特質{index}", weight=2.0),),
    ) for index, code in enumerate(codes))
    return SimpleNamespace(codes=codes, profiles=profiles, profile_for=lambda code: profiles[codes.index(code)])


class _Encoder:
    def __init__(self):
        self.calls = []
        self.result = np.eye(1, 384)[0]

    def encode(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return self.result


def _records(ids=(1, 2, 3)):
    return [
        {
            "_database_id": value, "pokedex_number": value,
            "name_zh": f"寶可夢{value}", "name_en": f"Pokemon {value}",
            "type_zh": "一般", "type_1": "Normal", "type_2": "",
            "category_zh": "測試", "genus": "Test", "image_url": "", "sprite_url": "",
            "description_zh": "尚未重建索引的新描述，禁止送到說明",
            "analysis_text": "最新編輯內容也不可送到說明",
        }
        for value in ids
    ]


def _candidate(pokemon_id, score, *, content="安靜守護夥伴"):
    evidence = FusedChunkHit(
        pokemon_id=pokemon_id, document_id=uuid4(), chunk_id=uuid4(),
        source_key="description_zh", document_kind="description_zh", language_code="zh-Hant",
        content=content, content_hash="a" * 64,
        dense_rank=1, dense_score=0.8, lexical_rank=1, lexical_score=0.5, rrf_score=score,
    )
    return PokemonRetrievalCandidate(
        pokemon_id=pokemon_id, retrieval_score=score, best_chunk_score=score,
        best_branch_rank=1, evidence=(evidence,),
    )


class _Session:
    def __init__(self):
        self.closed = False
        self.connection_options = []

    def connection(self, **kwargs):
        self.connection_options.append(kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True


class _Retriever:
    def __init__(self, text_candidates, mbti_candidates):
        self.text_candidates, self.mbti_candidates = text_candidates, mbti_candidates
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return self.text_candidates if len(self.calls) % 2 == 1 or not self.mbti_candidates else self.mbti_candidates


class _Profiles:
    def __init__(self, profiles):
        self.profiles, self.calls = profiles, []

    def load_profiles(self, ids, **kwargs):
        self.calls.append((ids, kwargs))
        return {value: self.profiles[value] for value in ids if value in self.profiles}


class HybridRecommendationEngineTests(unittest.TestCase):
    def _engine(self, candidates, *, mbti_candidates=(), indexed_profiles=None, loader=None):
        profile = PokemonPersonalityProfile(dataframe=pd.DataFrame(_records()), encoder=_Encoder())
        catalog = _catalog()
        scorer = MbtiScorer(catalog, np.eye(16, 384))
        sessions = []
        retriever = _Retriever(candidates, list(mbti_candidates))
        profiles = _Profiles(indexed_profiles if indexed_profiles is not None else {
            value: IndexedBehaviorProfile("安靜守護夥伴，完整但未召回的內容", tuple(np.eye(1, 384)[0]), ())
            for value in (1, 2, 3, 4)
        })

        def session_factory():
            session = _Session()
            sessions.append(session)
            return session

        engine = HybridRecommendationEngine(
            profile_engine=profile, session_factory=session_factory, embedding_model_id=9,
            retrieval_service_factory=lambda _session: retriever,
            mbti_profile_repository_factory=lambda _session: profiles,
            mbti_scorer=scorer, profile_records_loader=loader,
        )
        return engine, profile, sessions, retriever, profiles

    def test_text_only_encodes_once_uses_read_only_snapshot_and_stable_top_three(self):
        engine, profile, sessions, retriever, profiles = self._engine([
            _candidate(2, 0.02), _candidate(1, 0.03), _candidate(3, 0.01),
        ])
        results = engine.recommend("安靜守護夥伴")
        self.assertEqual([item["database_id"] for item in results], [1, 2, 3])
        self.assertEqual([item["rank"] for item in results], [1, 2, 3])
        self.assertEqual(len(profile.st_model.calls), 1)
        self.assertEqual(len(retriever.calls), 1)
        self.assertEqual(len(profiles.calls), 1)
        self.assertTrue(sessions[0].closed)
        self.assertEqual(sessions[0].connection_options, [{"execution_options": {
            "isolation_level": "REPEATABLE READ", "postgresql_readonly": True,
        }}])
        self.assertEqual(retriever.calls[0]["embedding_model_id"], 9)
        self.assertTrue(all(item["scores"]["mbti"] is None for item in results))
        self.assertTrue(all(item["selected_mbti"] is None and item["mbti_profile"] is None for item in results))

    def test_mbti_retrieves_separately_and_new_candidates_keep_zero_text_semantic(self):
        engine, profile, _sessions, retriever, profiles = self._engine(
            [_candidate(1, 0.03), _candidate(2, 0.02)],
            mbti_candidates=[_candidate(2, 0.03), _candidate(3, 0.03)],
        )
        results = engine.recommend("安靜守護夥伴", mbti="ｉｓｔｊ")
        by_id = {item["database_id"]: item for item in results}
        self.assertEqual(len(retriever.calls), 2)
        self.assertEqual(len(profile.st_model.calls), 1)
        self.assertEqual(retriever.calls[1]["query_text"], engine.mbti_catalog.profiles[0].matching_text)
        self.assertEqual(retriever.calls[1]["query_vector"], engine.mbti_scorer.prototype_vectors[0].tolist())
        self.assertEqual(set(profiles.calls[0][0]), {1, 2, 3})
        self.assertEqual(by_id[3]["scores"]["semantic"], 0)
        self.assertAlmostEqual(by_id[2]["scores"]["semantic"], 0.02 / (2 / 61), places=7)
        self.assertEqual(by_id[1]["selected_mbti"], "ISTJ")
        self.assertEqual(by_id[1]["mbti_profile"]["summary"], "詳細行為摘要0")

    def test_union_deduplicates_chunks_prefers_text_metadata_and_limits_evidence(self):
        text = _candidate(1, 0.03)
        duplicate_chunk = replace(text.evidence[0], dense_rank=10, dense_score=0.3)
        mbti_candidate = replace(text, evidence=(duplicate_chunk,) + tuple(
            _candidate(1, 0.01).evidence[0] for _ in range(4)
        ))
        merged = HybridRecommendationEngine._union_candidates([text], [mbti_candidate])
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0].evidence), 3)
        self.assertEqual(merged[0].evidence[0].dense_rank, 1)

    def test_scoring_reads_full_indexed_profile_but_explanation_only_allowed_evidence(self):
        engine, _profile, _sessions, _retriever, _profiles = self._engine([
            _candidate(1, 0.03), _candidate(2, 0.02), _candidate(3, 0.01),
        ])
        result = engine.recommend("安靜守護夥伴")[0]
        self.assertEqual(result["desc"], "安靜守護夥伴")
        self.assertEqual(result["analysis_text"], "安靜守護夥伴")
        self.assertNotIn("尚未重建", str(result))
        self.assertNotIn("完整但未召回", str(result))
        self.assertEqual(result["user_traits"], ["安靜"])
        self.assertEqual(result["pokemon_traits"], ["安靜"])
        self.assertEqual(result["matching_evidence"][0]["matched_traits"], ["安靜"])
        self.assertNotIn("type_weight_signals", result)

    def test_missing_behavior_profiles_fall_back_to_semantic(self):
        engine, _profile, _sessions, _retriever, _profiles = self._engine([
            _candidate(1, 0.03), _candidate(2, 0.02), _candidate(3, 0.01),
        ], indexed_profiles={})
        result = engine.recommend("安靜守護夥伴")[0]
        self.assertEqual(result["scores"]["personality"], 0)
        self.assertEqual(result["scores"]["semantic"], result["scores"]["total"])

    def test_validation_is_before_encoder_and_database_and_errors_hide_private_values(self):
        engine, profile, sessions, _retriever, _profiles = self._engine([])
        for kwargs in ({"user_text": "  "}, {"user_text": "安靜", "mbti": "私人錯誤值"}, {"user_text": "安靜", "top_k": 11}):
            with self.assertRaises(ValueError) as caught:
                engine.recommend(**kwargs)
            self.assertNotIn("私人錯誤值", str(caught.exception))
        self.assertEqual(profile.st_model.calls, [])
        self.assertEqual(sessions, [])

    def test_encoder_and_retrieval_errors_are_sanitized_and_sessions_close(self):
        engine, profile, sessions, retriever, _profiles = self._engine([])
        profile.st_model.result = [float("nan")] * 384
        with self.assertRaisesRegex(RetrievalUnavailableError, "query encoder"):
            engine.recommend("安靜守護夥伴")
        self.assertEqual(sessions, [])
        profile.st_model.result = np.eye(1, 384)[0]
        retriever.retrieve = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("private database details"))
        with self.assertRaisesRegex(RetrievalUnavailableError, "hybrid retrieval") as caught:
            engine.recommend("安靜守護夥伴")
        self.assertNotIn("private database", str(caught.exception))
        self.assertTrue(sessions[0].closed)

    def test_duplicate_candidates_and_incomplete_results_fail(self):
        duplicate = _candidate(1, 0.03)
        engine, *_ = self._engine([duplicate, duplicate, _candidate(2, 0.02)])
        with self.assertRaisesRegex(RetrievalUnavailableError, "duplicate"):
            engine.recommend("安靜守護夥伴")
        engine, *_ = self._engine([_candidate(1, 0.03), _candidate(2, 0.02)])
        with self.assertRaisesRegex(RetrievalUnavailableError, "only 2"):
            engine.recommend("安靜守護夥伴")

    def test_equal_scores_use_catalog_identity_and_new_ids_refresh_only_metadata(self):
        engine, *_ = self._engine([_candidate(value, 0.02) for value in (3, 1, 2)])
        self.assertEqual([row["database_id"] for row in engine.recommend("安靜守護夥伴")], [1, 2, 3])
        loader_calls = []
        engine, *_ = self._engine(
            [_candidate(value, 0.02) for value in (1, 2, 4)],
            loader=lambda: loader_calls.append(True) or _records((1, 2, 4)),
        )
        self.assertEqual([row["database_id"] for row in engine.recommend("安靜守護夥伴")], [1, 2, 4])
        self.assertEqual(loader_calls, [True])

    def test_new_ids_and_invalid_profile_embeddings_fail_safely(self):
        engine, *_ = self._engine([_candidate(value, 0.02) for value in (1, 2, 4)])
        with self.assertRaisesRegex(RetrievalUnavailableError, "snapshot is stale"):
            engine.recommend("安靜守護夥伴")
        engine, *_ = self._engine(
            [_candidate(value, 0.02) for value in (1, 2, 3)],
            indexed_profiles={1: IndexedBehaviorProfile("私密索引錯誤", (float("nan"),) * 384, ())},
        )
        with self.assertRaisesRegex(RetrievalUnavailableError, "personality scoring") as caught:
            engine.recommend("安靜守護夥伴")
        self.assertNotIn("私密索引", str(caught.exception))

    def test_default_startup_uses_bundle_and_never_opens_old_vocabulary(self):
        from app.main import _default_engine_factory
        from app.services.embedding import DEFAULT_MODEL_NAME
        from app.services.rag import GroundedExplanationService

        vector = np.eye(1, 384)[0]
        encoder = SimpleNamespace(encode=lambda texts, **_kwargs: (
            np.tile(vector, (len(texts), 1)) if isinstance(texts, list) else vector
        ))
        with (
            patch.dict(os.environ, {"EMBEDDING_MODEL": DEFAULT_MODEL_NAME, "EMBEDDING_MODEL_VERSION": "default"}, clear=True),
            patch("app.db.session.get_session_factory", return_value=lambda: _Session()),
            patch("app.repositories.mbti_profiles.MbtiProfileRepository") as pokemon,
            patch("app.repositories.VectorRepository") as vectors,
            patch("app.repositories.PersonalityRepository") as old_vocabulary,
            patch.object(PokemonPersonalityProfile, "_load_sentence_model", return_value=encoder),
            patch("app.services.mbti_catalog.get_mbti_catalog", return_value=_catalog()),
            patch.object(GroundedExplanationService, "from_env", return_value=GroundedExplanationService()),
        ):
            pokemon.return_value.metadata_records.return_value = _records()
            vectors.return_value.active_model.return_value = SimpleNamespace(
                id=9, model_name=DEFAULT_MODEL_NAME, model_version="default", normalize_embeddings=True,
            )
            vectors.return_value.ready_pokemon_count.return_value = 3
            engine = _default_engine_factory()
            self.assertEqual(engine.mbti_catalog.codes[0], "ISTJ")
            self.assertEqual(engine.mbti_scorer.prototype_vectors.shape, (16, 384))
            old_vocabulary.assert_not_called()


if __name__ == "__main__":
    unittest.main()
