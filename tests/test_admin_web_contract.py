from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AdminMbtiReferenceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = (ROOT / "app" / "static" / "js" / "admin.js").read_text(
            encoding="utf-8"
        )
        cls.template = (ROOT / "app" / "templates" / "admin.html").read_text(
            encoding="utf-8"
        )

    def test_mbti_reference_has_selection_loading_retry_and_no_editing_form(self):
        for element in (
            "admin-mbti-select", "admin-mbti-reload", "admin-mbti-status",
            "admin-mbti-details", "admin-mbti-terms", "admin-mbti-sources",
        ):
            self.assertIn(f'id="{element}"', self.template)
        self.assertIn("16 型 MBTI 詳細介紹（唯讀）", self.template)
        self.assertIn("本站不提供正式 MBTI 測評", self.template)
        self.assertIn("不是官方 MBTI 測評分數", self.template)
        self.assertIn("共 16 型", self.script)
        self.assertIn("catalog.traits.length !== 16", self.script)
        self.assertIn('addEventListener("click", loadMbtiCatalog)', self.script)
        self.assertNotIn('id="vocabulary-trait-form"', self.template)
        self.assertNotIn('id="vocabulary-synonym-form"', self.template)
        self.assertNotIn("儲存特質名稱", self.template)
        self.assertNotIn("加入同義詞", self.template)

    def test_reference_renders_all_prose_terms_sources_and_version(self):
        for field in (
            "summary", "information_style", "decision_style", "interaction_style",
            "action_style", "strengths", "blind_spots", "stress_pattern",
            "growth_tips", "weighted_terms", "source_urls", "reviewed_at",
        ):
            self.assertIn(f"profile.{field}", self.script)
        self.assertIn("catalog.catalog_version", self.script)
        self.assertIn("catalog.revision", self.script)
        self.assertIn("state.mbtiProfiles = catalog.traits", self.script)
        self.assertIn('await api("/personality/traits")', self.script)
        self.assertNotIn("vector_index", self.script)
        self.assertNotIn("vocabularySnapshot", self.script)
        self.assertNotIn("/synonyms", self.script)

    def test_read_only_content_uses_safe_dom_text_and_https_source_links(self):
        self.assertIn("summary.textContent = profile.summary", self.script)
        self.assertIn("term.textContent = item.term", self.script)
        self.assertIn("paragraph.textContent = value", self.script)
        self.assertIn('if (url.protocol !== "https:") return', self.script)
        self.assertIn('link.rel = "noopener noreferrer"', self.script)
        self.assertNotIn("innerHTML", self.script)
        self.assertNotIn("insertAdjacentHTML", self.script)

    def test_pokemon_editor_and_authenticated_mutation_controls_remain(self):
        self.assertIn('id="admin-editor"', self.template)
        self.assertIn('id="admin-reindex"', self.template)
        self.assertIn('headers["X-CSRF-Token"] = state.csrf', self.script)
        self.assertIn('method: id ? "PATCH" : "POST"', self.script)
        self.assertIn('api("/session", { method: "DELETE" })', self.script)

    def test_every_direct_script_element_reference_exists_in_template(self):
        references = set(re.findall(r'byId\("([^"\n]+)"\)', self.script))
        identifiers = set(re.findall(r'id="([^"\n]+)"', self.template))
        self.assertEqual(references - identifiers, set())


if __name__ == "__main__":
    unittest.main()
