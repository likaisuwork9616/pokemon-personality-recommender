from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.repositories.personality_admin import AdminPersonalityRepository
from app.schemas.admin import AdminPersonalitySynonymCreate, AdminPersonalitySynonymUpdate


class _Session:
    def __init__(self, active_count=1):
        self.active_count = active_count
        self.flushes = 0

    def scalar(self, _statement):
        return self.active_count

    def flush(self):
        self.flushes += 1

    def execute(self, _statement):
        return None


class PersonalityAdministrationTests(unittest.TestCase):
    def test_schema_rejects_blank_fields_empty_updates_and_invalid_weight(self):
        with self.assertRaises(ValueError):
            AdminPersonalitySynonymCreate(term="   ")
        with self.assertRaises(ValueError):
            AdminPersonalitySynonymCreate(term="可靠", weight=5.1)
        with self.assertRaises(ValueError):
            AdminPersonalitySynonymUpdate(original_term="可靠")
        with self.assertRaises(ValueError):
            AdminPersonalitySynonymUpdate(original_term="可靠", weight=None)

    def test_cannot_disable_the_last_active_synonym(self):
        session = _Session(active_count=1)
        item = SimpleNamespace(trait_code="loyal_guardian", term="承諾", language_code="zh-Hant", weight=2.0, is_active=True)

        with self.assertRaisesRegex(ValueError, "至少需要一個"):
            AdminPersonalityRepository(session).update_synonym(item, is_active=False)

        self.assertTrue(item.is_active)
        self.assertEqual(session.flushes, 0)

    def test_weight_language_and_activation_are_editable(self):
        session = _Session(active_count=2)
        item = SimpleNamespace(trait_code="loyal_guardian", term="承諾", language_code="zh-Hant", weight=2.0, is_active=True)

        AdminPersonalityRepository(session).update_synonym(
            item, term="守約", language_code="zh-Hant", weight=3.5, is_active=False
        )

        self.assertEqual((item.term, item.weight, item.is_active), ("守約", 3.5, False))
        self.assertEqual(session.flushes, 0)

    def test_term_normalization_collapses_case_and_compatibility_variants(self):
        display, normalized = AdminPersonalityRepository.normalize_term("  ＲＥＬＩＡＢＬＥ  ")
        self.assertEqual(display, "RELIABLE")
        self.assertEqual(normalized, "reliable")

        spaced_display, spaced_normalized = AdminPersonalityRepository.normalize_term(
            "  慢熟　 觀察  "
        )
        self.assertEqual(spaced_display, "慢熟 觀察")
        self.assertEqual(spaced_normalized, "慢熟 觀察")

    def test_normalization_revalidates_length_and_rejects_controls(self):
        for invalid in ("守\u200b護", "守\n護", "ß" * 80):
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaises(ValueError):
                    AdminPersonalityRepository.normalize_term(invalid)

    def test_semantic_noops_do_not_mutate_models(self):
        repository = AdminPersonalityRepository(_Session(active_count=2))
        trait = SimpleNamespace(name_zh="Guardian")
        synonym = SimpleNamespace(
            trait_code="loyal_guardian",
            term="Reliable",
            normalized_term="reliable",
            language_code="en",
            weight=2.0,
            is_active=True,
        )

        renamed = repository.rename_trait(trait, "ＧＵＡＲＤＩＡＮ")
        updated = repository.update_synonym(
            synonym,
            term="ＲＥＬＩＡＢＬＥ",
            language_code="en",
            weight=2.0,
            is_active=True,
        )

        self.assertFalse(renamed)
        self.assertFalse(updated)
        self.assertEqual(trait.name_zh, "Guardian")
        self.assertEqual(synonym.term, "Reliable")


if __name__ == "__main__":
    unittest.main()
