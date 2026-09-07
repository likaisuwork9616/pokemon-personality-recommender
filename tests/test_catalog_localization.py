from __future__ import annotations

import csv
import re
import unittest

from app.services.catalog_localization import (
    catalog_translation_count,
    has_catalog_translation,
    localize_ability_terms,
    localize_catalog_term,
    localize_catalog_terms,
)
from app.services.csv_importer import DEFAULT_CSV_PATH


def _codes(value: str | None) -> set[str]:
    return {
        item.strip().casefold()
        for item in re.split(r"[|,]", value or "")
        if item.strip() and item.strip().casefold() != "unknown"
    }


class CatalogLocalizationTests(unittest.TestCase):
    def test_known_terms_are_localized_and_unknown_terms_have_a_safe_fallback(self):
        abilities = localize_ability_terms(
            "Overgrow, Chlorophyll",
            "chlorophyll",
        )

        self.assertEqual(
            [(item.code, item.name_zh, item.is_hidden) for item in abilities],
            [
                ("overgrow", "茂盛", False),
                ("chlorophyll", "葉綠素", True),
            ],
        )
        self.assertEqual(
            [
                item.name_zh
                for item in localize_catalog_terms("Monster|Plant", "egg_group")
            ],
            ["怪獸", "植物"],
        )
        self.assertEqual(
            localize_catalog_term("grassland", "habitat").name_zh,
            "草原",
        )
        self.assertEqual(
            localize_catalog_term("medium-slow", "growth_rate").name_zh,
            "較慢",
        )
        fallback = localize_catalog_term("custom-region", "habitat")
        self.assertEqual(
            (fallback.code, fallback.name_zh),
            ("custom-region", "未收錄"),
        )

    def test_all_1025_pokemon_metadata_codes_have_traditional_chinese_names(self):
        with DEFAULT_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 1025)
        used_by_group = {
            "ability": set().union(
                *(
                    _codes(row["abilities"]) | _codes(row["hidden_ability"])
                    for row in rows
                )
            ),
            "egg_group": set().union(*(_codes(row["egg_groups"]) for row in rows)),
            "habitat": set().union(*(_codes(row["habitat"]) for row in rows)),
            "growth_rate": set().union(*(_codes(row["growth_rate"]) for row in rows)),
        }
        expected_counts = {
            "ability": 284,
            "egg_group": 15,
            "habitat": 9,
            "growth_rate": 6,
        }

        self.assertEqual(
            {group: len(codes) for group, codes in used_by_group.items()},
            expected_counts,
        )
        for group, codes in used_by_group.items():
            with self.subTest(group=group):
                missing = sorted(
                    code for code in codes if not has_catalog_translation(group, code)
                )
                self.assertEqual(missing, [])
                self.assertEqual(catalog_translation_count(group), expected_counts[group])
                for code in codes:
                    localized = localize_catalog_term(code, group)
                    self.assertIsNotNone(localized)
                    self.assertRegex(localized.name_zh, r"[\u3400-\u9fff]")


if __name__ == "__main__":
    unittest.main()
