from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AdminVocabularyDraftContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = (ROOT / "app" / "static" / "js" / "admin.js").read_text(
            encoding="utf-8"
        )
        cls.template = (ROOT / "app" / "templates" / "admin.html").read_text(
            encoding="utf-8"
        )

    def test_dirty_state_uses_normalized_snapshots_for_every_vocabulary_form(self):
        self.assertIn("vocabularySnapshot", self.script)
        self.assertIn("const captureVocabularyState", self.script)
        self.assertIn("normalizeTerm", self.script)
        self.assertIn("normalizeWeight", self.script)
        self.assertIn('traitName: normalizeText(byId("vocabulary-trait-name").value)', self.script)
        self.assertIn('term: normalizeTerm(byId("vocabulary-new-term").value)', self.script)
        self.assertIn('querySelectorAll("tr[data-original-term]")', self.script)
        self.assertIn("serializedVocabularyState() !== JSON.stringify(state.vocabularySnapshot)", self.script)
        self.assertNotIn("dataset.dirty", self.script)

    def test_discard_guards_cover_reload_switch_logout_and_page_exit(self):
        self.assertIn('confirmVocabularyDiscard("重新載入人格詞庫")', self.script)
        self.assertIn('confirmVocabularyDiscard("切換人格特質")', self.script)
        self.assertIn('confirmVocabularyDiscard("登出後台")', self.script)
        self.assertIn('window.addEventListener("beforeunload"', self.script)
        self.assertIn("人格詞庫尚有未儲存的變更", self.script)
        self.assertIn("離開頁面會捨棄這些內容", self.script)

    def test_successful_saves_commit_only_the_saved_draft_section(self):
        self.assertIn("commitTraitSnapshot();", self.script)
        self.assertIn("commitNewSynonymSnapshot();", self.script)
        self.assertIn("commitSynonymSnapshot(previousTerm, row);", self.script)
        self.assertIn("replaceTraitSynonym(trait, previousTerm, updated);", self.script)
        self.assertIn("appendSynonymRow(trait, created)", self.script)
        self.assertNotIn("await loadVocabulary(trait.code)", self.script)

    def test_synonym_update_keeps_term_in_the_request_body_and_validates_inputs(self):
        endpoint = "/personality/traits/${encodeURIComponent(trait.code)}/synonyms"
        self.assertIn(endpoint, self.script)
        self.assertIn("original_term: previousTerm", self.script)
        self.assertNotIn("/synonyms/${encodeURIComponent(previousTerm)}", self.script)
        self.assertIn("input.reportValidity()", self.script)

    def test_weight_inputs_match_the_positive_api_contract(self):
        self.assertIn('weight.min = "0.01"', self.script)
        self.assertIn('weight.max = "5"', self.script)
        self.assertIn('weight.step = "0.01"', self.script)
        self.assertIn('min="0.01" max="5" step="0.01"', self.template)
        self.assertIn("權重（大於 0，最高 5）", self.template)


if __name__ == "__main__":
    unittest.main()
