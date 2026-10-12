from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from app.services.personality_profile import PokemonPersonalityProfile


class ProfileMetadataTests(unittest.TestCase):
    def _row(self):
        return {"_database_id": 1, "pokedex_number": 1, "name_zh": "妙蛙種子",
                "name_en": "Bulbasaur", "type_zh": "草, 毒"}

    def test_profile_is_display_metadata_and_encoder_without_old_personality_rules(self):
        encoder = object()
        source = pd.DataFrame([self._row()])
        profile = PokemonPersonalityProfile(dataframe=source, encoder=encoder)
        self.assertIs(profile.st_model, encoder)
        self.assertFalse(hasattr(profile, "persona_vectors"))
        self.assertFalse(hasattr(profile, "type_weight_signals"))
        source.loc[0, "name_zh"] = "外部改動"
        self.assertEqual(profile.df.iloc[0]["name_zh"], "妙蛙種子")
        self.assertEqual(profile.safe_get(profile.df.iloc[0], "image_url"), "")

    def test_invalid_metadata_does_not_load_or_download_a_model(self):
        with patch.object(PokemonPersonalityProfile, "_load_sentence_model") as load:
            with self.assertRaisesRegex(ValueError, "_database_id"):
                PokemonPersonalityProfile(dataframe=pd.DataFrame([{"name_zh": "資料不足"}]))
            load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
