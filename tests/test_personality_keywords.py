from __future__ import annotations

import unittest

import numpy as np

from pokedex_online import PokemonRecommender, TRAITS


class PersonalityKeywordTests(unittest.TestCase):
    def setUp(self) -> None:
        # The keyword extractor has no dependency on the model or dataframe.
        self.recommender = PokemonRecommender.__new__(PokemonRecommender)

    def test_natural_chinese_commitment_and_sharing_phrases_activate_traits(self):
        vector = self.recommender.text_to_persona_vector(
            "我慢熟但重承諾，我喜歡與人分享我喜歡的事物"
        )

        self.assertAlmostEqual(float(np.linalg.norm(vector)), 1.0)
        active_traits = {
            TRAITS[index]
            for index, value in enumerate(vector)
            if value > 0
        }
        self.assertEqual(
            active_traits,
            {"社交魅力型", "忠誠守護者", "孤獨思考者"},
        )


if __name__ == "__main__":
    unittest.main()
