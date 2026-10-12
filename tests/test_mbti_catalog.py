from __future__ import annotations

import copy
import json
import re
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

from app.personality_vocabulary import canonicalize_personality_text
from app.services import mbti_catalog
from app.services.mbti_catalog import MBTI_CODES, get_mbti_catalog, normalize_mbti


class MbtiCatalogTests(unittest.TestCase):
    def setUp(self):
        get_mbti_catalog.cache_clear()
        self.payload = json.loads(mbti_catalog._DATA_PATH.read_text(encoding="utf-8"))

    def tearDown(self):
        get_mbti_catalog.cache_clear()

    def test_catalog_contains_all_16_ordered_detailed_bilingual_profiles(self):
        catalog = get_mbti_catalog()

        self.assertEqual(catalog.version, "mbti-zh-hant-v1")
        self.assertEqual(catalog.revision, 1)
        self.assertEqual(catalog.reviewed_at, "2026-10-12")
        self.assertEqual(catalog.codes, MBTI_CODES)
        self.assertEqual(catalog.codes, tuple(sorted(catalog.codes)))
        self.assertRegex(catalog.content_hash, r"^[0-9a-f]{64}$")
        for profile in catalog.profiles:
            with self.subTest(code=profile.code):
                prose = " ".join((
                    profile.matching_text, profile.stress_pattern,
                    *profile.blind_spots, *profile.growth_tips,
                ))
                self.assertGreaterEqual(len(re.findall(r"[\u3400-\u9fff]", prose)), 250)
                self.assertGreaterEqual(len(profile.weighted_terms), 12)
                self.assertTrue(any(re.search(r"[A-Za-z]", item.term) for item in profile.weighted_terms))
                self.assertTrue(any(re.search(r"[\u3400-\u9fff]", item.term) for item in profile.weighted_terms))
                canonical_terms = [canonicalize_personality_text(item.term) for item in profile.weighted_terms]
                self.assertEqual(len(canonical_terms), len(set(canonical_terms)))
                self.assertTrue(all(0 < item.weight <= 5 for item in profile.weighted_terms))
                self.assertTrue(all(item.upper() not in MBTI_CODES for item in canonical_terms))
                self.assertIn(f"https://www.mbtionline.com/mbti-types/{profile.code.lower()}", profile.source_urls)
                self.assertEqual(profile.reviewed_at, "2026-10-12")

    def test_cached_catalog_is_deeply_immutable_and_can_lookup_normalized_input(self):
        catalog = get_mbti_catalog()

        self.assertIs(catalog, get_mbti_catalog())
        self.assertIs(catalog.profile_for(" ｉｎｆｐ－ｔ "), catalog.profile_for("INFP"))
        self.assertIsInstance(catalog.profiles, tuple)
        profile = catalog.profiles[0]
        for attribute in ("strengths", "blind_spots", "growth_tips", "weighted_terms", "source_urls"):
            self.assertIsInstance(getattr(profile, attribute), tuple)
        with self.assertRaises(FrozenInstanceError):
            catalog.version = "changed"
        with self.assertRaises(FrozenInstanceError):
            profile.summary = "changed"
        with self.assertRaises(FrozenInstanceError):
            profile.weighted_terms[0].weight = 5
        with self.assertRaisesRegex(ValueError, "有效"):
            catalog.profile_for(" ")

    def test_matching_text_excludes_negative_cautions_and_coaching(self):
        profile = replace(
            get_mbti_catalog().profile_for("INFP"),
            blind_spots=("盲點專用的否定敘述",),
            stress_pattern="壓力專用的否定敘述",
            growth_tips=("成長建議專用敘述",),
        )

        for included in (
            profile.summary, profile.information_style, profile.decision_style,
            profile.interaction_style, profile.action_style, *profile.strengths,
        ):
            self.assertIn(included, profile.matching_text)
        for excluded in (*profile.blind_spots, profile.stress_pattern, *profile.growth_tips):
            self.assertNotIn(excluded, profile.matching_text)

    def test_hash_ignores_object_key_order_but_detects_content_and_revision(self):
        original = mbti_catalog._catalog_from_payload(self.payload)
        reordered = dict(reversed(list(self.payload.items())))

        self.assertEqual(original.content_hash, mbti_catalog._catalog_from_payload(reordered).content_hash)
        changed = copy.deepcopy(self.payload)
        changed["profiles"][0]["summary"] += " 內容修訂。"
        self.assertNotEqual(original.content_hash, mbti_catalog._catalog_from_payload(changed).content_hash)
        changed = copy.deepcopy(self.payload)
        changed["revision"] += 1
        self.assertNotEqual(original.content_hash, mbti_catalog._catalog_from_payload(changed).content_hash)

    def test_missing_invalid_or_reordered_type_fails_before_use(self):
        variants = []
        missing = copy.deepcopy(self.payload)
        missing["profiles"].pop()
        variants.append(missing)
        duplicate = copy.deepcopy(self.payload)
        duplicate["profiles"][1] = copy.deepcopy(duplicate["profiles"][0])
        variants.append(duplicate)
        invalid = copy.deepcopy(self.payload)
        invalid["profiles"][0]["code"] = "ABCD"
        variants.append(invalid)
        full_width = copy.deepcopy(self.payload)
        full_width["profiles"][0]["code"] = "ＥＮＦＪ"
        variants.append(full_width)
        reordered = copy.deepcopy(self.payload)
        reordered["profiles"].reverse()
        variants.append(reordered)

        for payload in variants:
            with self.subTest(codes=[item["code"] for item in payload["profiles"]]):
                with self.assertRaises(RuntimeError):
                    mbti_catalog._catalog_from_payload(payload)

    def test_incomplete_profile_text_and_sources_are_rejected(self):
        replacements = (
            ("summary", " "), ("information_style", None),
            ("decision_style", ""), ("interaction_style", 12),
            ("action_style", []), ("stress_pattern", ""),
            ("strengths", []), ("blind_spots", [" "]),
            ("growth_tips", "文字"), ("source_urls", ["http://example.com"]),
            ("source_urls", ["https://"]), ("reviewed_at", "2026-02-30"),
        )
        for field, replacement in replacements:
            with self.subTest(field=field, value=replacement):
                payload = copy.deepcopy(self.payload)
                payload["profiles"][0][field] = replacement
                with self.assertRaises(RuntimeError):
                    mbti_catalog._catalog_from_payload(payload)

        too_short = copy.deepcopy(self.payload)
        for field in mbti_catalog._TEXT_FIELDS:
            too_short["profiles"][0][field] = "說明"
        for field in mbti_catalog._LIST_FIELDS:
            too_short["profiles"][0][field] = ["說明"]
        with self.assertRaisesRegex(RuntimeError, "250"):
            mbti_catalog._catalog_from_payload(too_short)

    def test_term_weights_reject_nonfinite_boolean_and_out_of_range_numbers(self):
        for weight in (0, -1, 5.01, float("nan"), float("inf"), True, "3", 10 ** 400):
            with self.subTest(weight=weight):
                payload = copy.deepcopy(self.payload)
                payload["profiles"][0]["weighted_terms"][0]["weight"] = weight
                with self.assertRaisesRegex(RuntimeError, "權重"):
                    mbti_catalog._catalog_from_payload(payload)

    def test_public_name_and_term_length_limits_are_enforced_before_use(self):
        payload = copy.deepcopy(self.payload)
        payload["profiles"][0]["name_zh"] = "人" * 40
        payload["profiles"][0]["weighted_terms"][0]["term"] = "行" * 80
        accepted = mbti_catalog._catalog_from_payload(payload)
        self.assertEqual(len(accepted.profiles[0].name_zh), 40)
        self.assertEqual(len(accepted.profiles[0].weighted_terms[0].term), 80)

        invalid = copy.deepcopy(self.payload)
        invalid["profiles"][0]["name_zh"] = "人" * 41
        with self.assertRaisesRegex(RuntimeError, "40"):
            mbti_catalog._catalog_from_payload(invalid)
        # NFKC expands the ligature to three letters; casefold expands ß.
        for term in ("行" * 81, "ﬃ" * 27, "ß" * 41):
            with self.subTest(term=term):
                invalid = copy.deepcopy(self.payload)
                invalid["profiles"][0]["weighted_terms"][0]["term"] = term
                with self.assertRaisesRegex(RuntimeError, "80"):
                    mbti_catalog._catalog_from_payload(invalid)

    def test_source_parser_and_port_errors_are_clear_catalog_failures(self):
        for url in (
            "https://[invalid", "https://[::1]:invalid", "https://example.com:65536",
            "https://example.com:-1", "https://example.com:not-a-port",
            "https://example .com", "https://user:password@example.com",
        ):
            with self.subTest(url=url):
                invalid = copy.deepcopy(self.payload)
                invalid["profiles"][0]["source_urls"] = [url]
                with self.assertRaisesRegex(RuntimeError, "HTTPS"):
                    mbti_catalog._catalog_from_payload(invalid)

        for url in ("https://example.com:443/reference", "https://[::1]:8443/reference"):
            with self.subTest(url=url):
                payload = copy.deepcopy(self.payload)
                payload["profiles"][0]["source_urls"] = [url]
                catalog = mbti_catalog._catalog_from_payload(payload)
                self.assertEqual(catalog.profiles[0].source_urls, (url,))

    def test_terms_reject_nfkc_casefold_whitespace_duplicates_and_bare_codes(self):
        for terms in (("GUIDE", "ｇｕｉｄｅ"), ("quiet support", "Quiet　 Support")):
            with self.subTest(terms=terms):
                payload = copy.deepcopy(self.payload)
                payload["profiles"][0]["weighted_terms"][0]["term"] = terms[0]
                payload["profiles"][0]["weighted_terms"][1]["term"] = terms[1]
                with self.assertRaisesRegex(RuntimeError, "重複"):
                    mbti_catalog._catalog_from_payload(payload)
        for term in ("INFP", "ｉｎｆｐ", "ENFP-T", "bad\u200bterm", " "):
            with self.subTest(term=term):
                payload = copy.deepcopy(self.payload)
                payload["profiles"][0]["weighted_terms"][0]["term"] = term
                with self.assertRaises(RuntimeError):
                    mbti_catalog._catalog_from_payload(payload)

    def test_loader_reports_missing_and_malformed_content_and_preserves_cache(self):
        catalog = get_mbti_catalog()
        with patch.object(mbti_catalog, "_DATA_PATH", Path("missing-mbti-file.json")):
            self.assertIs(catalog, get_mbti_catalog())
            get_mbti_catalog.cache_clear()
            with self.assertRaisesRegex(RuntimeError, "無法讀取"):
                get_mbti_catalog()
        with patch.object(Path, "read_text", return_value="{invalid"):
            with self.assertRaisesRegex(RuntimeError, "無法讀取"):
                get_mbti_catalog()


class NormalizeMbtiTests(unittest.TestCase):
    def test_known_user_inputs_normalize_without_inferring_a_type(self):
        for value in (None, "", "  ", "　"):
            with self.subTest(value=value):
                self.assertIsNone(normalize_mbti(value))
        for value in ("infp", " INFP ", "ｉｎｆｐ", "INFP-A", "ｉｎｆｐ－ｔ"):
            with self.subTest(value=value):
                self.assertEqual(normalize_mbti(value), "INFP")
        for code in MBTI_CODES:
            self.assertEqual(normalize_mbti(code), code)

    def test_invalid_types_suffixes_and_non_string_values_are_clear_errors(self):
        for value in ("ABCD", "INFP-X", "INFP-AT", "IN FP", "我是 INFP", "INFP\u200b", 12, True, []):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "MBTI"):
                    normalize_mbti(value)


if __name__ == "__main__":
    unittest.main()
