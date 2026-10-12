from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np

from app.services.mbti_scoring import MbtiScorer, cosine_affinity


def _catalog():
    codes = ("ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP",
             "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ")
    profiles = tuple(SimpleNamespace(
        code=code, matching_text=f"詳細行為內容{index}",
        weighted_terms=(SimpleNamespace(term="可靠" if index == 0 else f"特質{index}", weight=2.0),),
    ) for index, code in enumerate(codes))
    return SimpleNamespace(codes=codes, profiles=profiles)


class MbtiScoringTests(unittest.TestCase):
    def setUp(self):
        self.catalog = _catalog()
        self.prototypes = np.eye(16, 384)
        self.scorer = MbtiScorer(self.catalog, self.prototypes)

    def test_semantics_and_keywords_use_fixed_weights_on_both_sides(self):
        vector = self.scorer.affinity("可靠", self.prototypes[0])
        self.assertAlmostEqual(vector[0], 1.0)
        self.assertEqual(vector[1], 0)
        np.testing.assert_array_equal(vector, self.scorer.affinity("可靠", self.prototypes[0]))
        self.assertAlmostEqual(self.scorer.affinity("無關詞", self.prototypes[0])[0], 0.8)

    def test_normalized_duplicate_terms_and_repetitions_are_counted_once(self):
        self.catalog.profiles[0].weighted_terms = (
            SimpleNamespace(term="ＲＥＬＩＡＢＬＥ", weight=1.0),
            SimpleNamespace(term="reliable", weight=3.0),
            SimpleNamespace(term="合作", weight=1.0),
        )
        first = self.scorer.affinity("RELIABLE reliable", np.zeros(384))
        self.assertAlmostEqual(first[0], 0.15)
        np.testing.assert_array_equal(first, self.scorer.affinity("reliable", np.zeros(384)))

    def test_detailed_matching_text_is_encoded_and_prototypes_are_immutable(self):
        calls = []
        encoder = SimpleNamespace(encode=lambda texts, **kwargs: calls.append((texts, kwargs)) or self.prototypes)
        scorer = MbtiScorer.from_encoder(self.catalog, encoder)
        self.assertEqual(calls[0][0], [profile.matching_text for profile in self.catalog.profiles])
        with self.assertRaises(ValueError):
            scorer.prototype_vectors[0, 0] = 2
        self.prototypes[0] = self.prototypes[1]
        self.assertEqual(scorer.prototype_vectors[0, 0], 1)

    def test_actual_behavior_terms_are_returned_without_inferred_type(self):
        self.assertEqual(self.scorer.matched_terms("我是可靠的人，也是 ISTJ"), ["可靠"])

    def test_long_profile_tail_contributes_without_encoder_truncation(self):
        self.catalog.profiles[0].matching_text = "前段內容" * 80 + "尾段重要偏好"
        calls = []

        def encode(texts, **_kwargs):
            calls.extend(texts)
            return np.asarray([
                self.prototypes[1] if "尾段重要偏好" in text else self.prototypes[0]
                for text in texts
            ])

        scorer = MbtiScorer.from_encoder(self.catalog, SimpleNamespace(encode=encode))
        self.assertTrue(all(len(text) <= 64 for text in calls))
        self.assertGreater(scorer.prototype_vectors[0, 1], 0)

    def test_text_is_primary_and_optional_mbti_adds_exact_quarter(self):
        user, pokemon = np.eye(16)[0], np.eye(16)[0]
        without = self.scorer.score_components(0.4, user, pokemon)
        with_mbti = self.scorer.score_components(0.4, user, pokemon, mbti="ISTJ")
        self.assertIsNone(without["mbti"])
        self.assertAlmostEqual(without["total"], 0.55)
        self.assertAlmostEqual(with_mbti["total"], 0.75 * 0.55 + 0.25)

    def test_zero_affinity_falls_back_to_semantic_and_invalid_shapes_fail(self):
        scores = self.scorer.score_components(0.4, np.zeros(16), np.ones(16))
        self.assertEqual(scores["total"], 0.4)
        with self.assertRaises(ValueError):
            self.scorer.affinity("可靠", [1.0])
        with self.assertRaises(ValueError):
            cosine_affinity([float("nan")] * 16, [1.0] * 16)


if __name__ == "__main__":
    unittest.main()
