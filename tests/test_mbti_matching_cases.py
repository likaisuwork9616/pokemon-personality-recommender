"""Behavioral acceptance cases using the checked-in MBTI reference content.

The tiny semantic encoder substitutes a few human-readable behavior concepts
for the downloaded model. Retrieval uses that semantic similarity against a
fixed indexed corpus; it does not choose answers from an MBTI label.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from app.repositories.mbti_profiles import IndexedBehaviorProfile
from app.services.mbti_catalog import get_mbti_catalog
from app.services.personality_profile import PokemonPersonalityProfile
from app.services.recommendation import HybridRecommendationEngine
from tests.test_recommendation_service import _candidate, _records


CARE_QUERY = "朋友心情低落時，我會放慢步調陪他坐一會，讓對方願意說話。"
LOGIC_QUERY = "碰到難題時，我會自己整理已知條件，逐項驗算，直到理由都說得通。"
NEUTRAL_QUERY = "我在心情、理由與見聞之間尋求平衡，也願意聽取各方觀點。"
CORPUS = {
    113: "看見有人難過時會靠近，耐心陪伴，讓夥伴感到安心。",
    376: "沉默地拆解資訊，反覆驗證推論，找到問題的根本原因。",
    133: "興奮地拜訪陌生地方，想把新奇見聞分享給大家。",
}


class _ConceptEncoder:
    """A deterministic 384-dimensional semantic double with no input cache."""

    concepts = (
        ("感受", "關心", "照顧", "陪伴", "價值", "關係", "傾聽", "難過", "安心", "心情", "對方", "說話", "坐一會", "支持", "關懷"),
        ("邏輯", "分析", "推論", "驗證", "模型", "原理", "拆解", "條件", "驗算", "理由", "根本", "論證", "證據", "系統", "思考", "資訊"),
        ("靈感", "好奇", "可能", "探索", "新", "陌生", "想像", "熱情", "變化", "走走", "新鮮", "見聞", "試驗", "即興", "創意", "開拓"),
    )

    @classmethod
    def vector(cls, text):
        vector = np.zeros(384)
        for index, words in enumerate(cls.concepts):
            vector[index] = sum(str(text).count(word) for word in words)
        vector[383] = 0.05
        if "PRIVATE-CASE-7621" in str(text):
            vector[382] = 0.123
        return vector / np.linalg.norm(vector)

    def encode(self, text, **_kwargs):
        if isinstance(text, list):
            return np.asarray([self.vector(value) for value in text])
        return self.vector(text)


class _ReadOnlySession:
    def __init__(self):
        self.closed = False
        self.options = None

    def connection(self, *, execution_options):
        self.options = execution_options

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def commit(self):
        raise AssertionError("recommendations must not commit")

    def add(self, *_args):
        raise AssertionError("recommendations must not persist user data")

    def flush(self):
        raise AssertionError("recommendations must not flush")


class _ConceptRetriever:
    def retrieve(self, *, query_vector, **_kwargs):
        candidates = []
        for pokemon_id, text in CORPUS.items():
            similarity = float(np.clip(np.dot(query_vector, _ConceptEncoder.vector(text)), 0, 1))
            # Ranks within a larger background corpus create a realistic RRF
            # range while these three indexed profiles remain visible.
            branch_rank = 1 + round((1 - similarity) * 49)
            candidate = _candidate(pokemon_id, 2 / (60 + branch_rank), content=text)
            evidence = replace(
                candidate.evidence[0], dense_rank=branch_rank, lexical_rank=branch_rank,
                dense_score=similarity,
            )
            candidates.append(replace(candidate, best_branch_rank=branch_rank, evidence=(evidence,)))
        return candidates


class _IndexedProfiles:
    def load_profiles(self, ids, **_kwargs):
        return {
            pokemon_id: IndexedBehaviorProfile(
                CORPUS[pokemon_id], tuple(_ConceptEncoder.vector(CORPUS[pokemon_id])), (),
            )
            for pokemon_id in ids
        }


class MbtiMatchingCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = get_mbti_catalog()

    def engine(self, *, catalog=None, changed_types=False):
        encoder = _ConceptEncoder()
        records = _records(CORPUS)
        if changed_types:
            for record in records:
                record.update(type_zh="火, 幽靈", type_1="Fire", type_2="Ghost")
        profile = PokemonPersonalityProfile(dataframe=pd.DataFrame(records), encoder=encoder)
        sessions = []

        def session_factory():
            session = _ReadOnlySession()
            sessions.append(session)
            return session

        engine = HybridRecommendationEngine(
            profile_engine=profile, session_factory=session_factory, embedding_model_id=9,
            mbti_catalog=catalog or self.catalog,
            retrieval_service_factory=lambda _session: _ConceptRetriever(),
            mbti_profile_repository_factory=lambda _session: _IndexedProfiles(),
        )
        return engine, sessions

    def test_text_only_matches_care_and_analysis_without_assigning_a_user_type(self):
        engine, _sessions = self.engine()
        care = engine.recommend(CARE_QUERY)
        logic = engine.recommend(LOGIC_QUERY)
        self.assertEqual(care[0]["database_id"], 113)
        self.assertEqual(logic[0]["database_id"], 376)
        self.assertNotEqual([row["database_id"] for row in care], [row["database_id"] for row in logic])
        for result in care + logic:
            self.assertIsNone(result["selected_mbti"])
            self.assertIsNone(result["scores"]["mbti"])
            self.assertFalse(any(re.fullmatch(r"[EI][SN][TF][JP]", trait) for trait in result["user_traits"]))

    def test_same_selected_type_still_respects_different_personal_descriptions(self):
        engine, _sessions = self.engine()
        care = engine.recommend(CARE_QUERY, mbti="ISFJ")
        logic = engine.recommend(LOGIC_QUERY, mbti="ISFJ")
        self.assertEqual(care[0]["database_id"], 113)
        self.assertEqual(logic[0]["database_id"], 376)

    def test_same_balanced_description_changes_with_selected_reference_type(self):
        engine, _sessions = self.engine()
        care_type = engine.recommend(NEUTRAL_QUERY, mbti="ISFJ")
        logic_type = engine.recommend(NEUTRAL_QUERY, mbti="INTP")
        self.assertEqual(care_type[0]["database_id"], 113)
        self.assertEqual(logic_type[0]["database_id"], 376)

    def test_clear_analytic_description_takes_priority_over_opposite_social_type(self):
        engine, _sessions = self.engine()
        results = engine.recommend(LOGIC_QUERY, mbti="ESFP")
        self.assertEqual(results[0]["database_id"], 376)
        self.assertEqual(results[0]["selected_mbti"], "ESFP")
        self.assertGreater(results[0]["scores"]["total"], results[1]["scores"]["total"])

    def test_editing_detailed_preferences_changes_match_with_identical_keywords(self):
        original = self.catalog.profile_for("INTP")
        caring = self.catalog.profile_for("ISFJ")
        changed = replace(
            original, summary=caring.summary, information_style=caring.information_style,
            decision_style=caring.decision_style, interaction_style=caring.interaction_style,
            action_style=caring.action_style, strengths=caring.strengths,
        )
        edited_catalog = replace(
            self.catalog,
            profiles=tuple(changed if profile.code == "INTP" else profile for profile in self.catalog.profiles),
            revision=self.catalog.revision + 1, content_hash="test-detailed-content-change",
        )
        before, _ = self.engine()
        after, _ = self.engine(catalog=edited_catalog)
        self.assertEqual(original.weighted_terms, changed.weighted_terms)
        self.assertEqual(before.recommend(NEUTRAL_QUERY, mbti="INTP")[0]["database_id"], 376)
        self.assertEqual(after.recommend(NEUTRAL_QUERY, mbti="INTP")[0]["database_id"], 113)

    def test_elemental_type_changes_do_not_change_matching_order_or_scores(self):
        original, _ = self.engine()
        changed, _ = self.engine(changed_types=True)
        before = original.recommend(LOGIC_QUERY, mbti="ISFJ")
        after = changed.recommend(LOGIC_QUERY, mbti="ISFJ")
        self.assertEqual(
            [(row["database_id"], row["scores"]) for row in before],
            [(row["database_id"], row["scores"]) for row in after],
        )
        self.assertNotEqual(before[0]["type"], after[0]["type"])

    def test_private_input_and_embedding_stay_request_local_without_writes(self):
        engine, sessions = self.engine()
        private = LOGIC_QUERY + " PRIVATE-CASE-7621"
        prototypes = engine.mbti_scorer.prototype_vectors.copy()
        metadata = engine.profile_engine.df.copy(deep=True)
        original_attributes = set(vars(engine))
        with (
            patch.object(Path, "write_text", side_effect=AssertionError("no user file writes")),
            patch.object(Path, "write_bytes", side_effect=AssertionError("no vector file writes")),
        ):
            engine.recommend(private, mbti="INTP")
            following = engine.recommend(CARE_QUERY)
        self.assertEqual(following[0]["database_id"], 113)
        self.assertEqual(set(vars(engine)), original_attributes)
        np.testing.assert_array_equal(engine.mbti_scorer.prototype_vectors, prototypes)
        pd.testing.assert_frame_equal(engine.profile_engine.df, metadata)
        private_vector = _ConceptEncoder.vector(private)
        for owner in (engine, engine.profile_engine, engine.mbti_scorer, engine.profile_engine.st_model):
            self.assertNotIn("PRIVATE-CASE-7621", repr(vars(owner)))
            for value in vars(owner).values():
                if isinstance(value, np.ndarray) and value.shape == (384,):
                    self.assertFalse(np.array_equal(value, private_vector))
        self.assertTrue(all(session.closed and session.options["postgresql_readonly"] for session in sessions))


if __name__ == "__main__":
    unittest.main()
