from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from app.services.personality_profile import (
    TYPE_PERSONALITY_WEIGHTS,
    TYPE_PERSONALITY_WEIGHTS_VERSION,
    PokemonPersonalityProfile,
)


def _row(*, pokedex_number: int, pokemon_type: str) -> dict[str, object]:
    return {
        "pokedex_number": pokedex_number,
        "name_zh": f"測試寶可夢{pokedex_number}",
        "name_en": f"Testmon {pokedex_number}",
        "type_zh": pokemon_type,
        "category_zh": "測試寶可夢",
        "genus": "Test Pokémon",
        "description_zh": "沒有命中人格關鍵字的描述",
        "flavor_text_en": "No personality keyword matches.",
        "analysis_text": "無額外分析",
        "image_url": f"https://example.test/{pokedex_number}.png",
    }


class TypePersonalityWeightTests(unittest.TestCase):
    def _profile(self, *rows: dict[str, object]) -> PokemonPersonalityProfile:
        with patch.object(
            PokemonPersonalityProfile,
            "_load_sentence_model",
            return_value=object(),
        ):
            return PokemonPersonalityProfile(
                dataframe=pd.DataFrame(rows),
                personality_traits=tuple(f"特質{index}" for index in range(16)),
                persona_keywords={
                    f"特質{index}": (f"不會命中的詞{index}",)
                    for index in range(16)
                },
            )

    def test_all_eighteen_types_define_safe_sixteen_dimension_weights(self):
        self.assertEqual(len(TYPE_PERSONALITY_WEIGHTS), 18)
        for type_name, weights in TYPE_PERSONALITY_WEIGHTS.items():
            with self.subTest(type_name=type_name):
                self.assertEqual(len(weights), 16)
                self.assertTrue(all(0 < weight <= 5 for weight in weights))

    def test_single_type_weight_is_part_of_the_backend_personality_vector(self):
        profile = self._profile(
            _row(pokedex_number=1, pokemon_type="火"),
            _row(pokedex_number=2, pokemon_type="水"),
        )

        expected_fire = PokemonPersonalityProfile.normalize_vec(
            np.asarray(TYPE_PERSONALITY_WEIGHTS["火"], dtype=float)
        )
        expected_water = PokemonPersonalityProfile.normalize_vec(
            np.asarray(TYPE_PERSONALITY_WEIGHTS["水"], dtype=float)
        )
        np.testing.assert_allclose(profile.persona_vectors[0], expected_fire)
        np.testing.assert_allclose(profile.persona_vectors[1], expected_water)
        self.assertFalse(np.allclose(profile.persona_vectors[0], profile.persona_vectors[1]))

    def test_dual_types_add_both_weight_profiles_before_normalization(self):
        profile = self._profile(_row(pokedex_number=3, pokemon_type="草, 毒"))
        combined = (
            np.asarray(TYPE_PERSONALITY_WEIGHTS["草"], dtype=float)
            + np.asarray(TYPE_PERSONALITY_WEIGHTS["毒"], dtype=float)
        )
        expected = PokemonPersonalityProfile.normalize_vec(
            combined
        )

        np.testing.assert_allclose(profile.persona_vectors[0], expected)

        signals = profile.type_weight_signals(profile.df.iloc[0])
        self.assertEqual(signals["version"], TYPE_PERSONALITY_WEIGHTS_VERSION)
        self.assertEqual(
            [(item["role"], item["type_zh"]) for item in signals["type_profiles"]],
            [("主屬性", "草"), ("副屬性", "毒")],
        )
        self.assertEqual(
            signals["type_profiles"][0]["trait_weights"]["特質0"],
            TYPE_PERSONALITY_WEIGHTS["草"][0],
        )
        expected_top_index = int(np.argmax(combined))
        self.assertEqual(
            signals["combined_top_traits"][0]["trait"],
            f"特質{expected_top_index}",
        )


if __name__ == "__main__":
    unittest.main()
