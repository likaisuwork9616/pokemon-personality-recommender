from __future__ import annotations

import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


ROOT = Path(__file__).resolve().parents[1]


class RecommendationWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = TestClient(create_app(lambda: object()))
        self.client = self.context.__enter__()

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)

    def test_root_is_the_formal_top_three_recommendation_page(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="recommendation-form"', response.text)
        self.assertIn('id="personality-text"', response.text)
        self.assertIn('id="generate-explanation" type="checkbox"', response.text)
        self.assertNotIn('id="generate-explanation" type="checkbox" checked', response.text)
        self.assertIn('id="recommendation-grid"', response.text)
        self.assertIn("原始文字與 query vector", response.text)
        self.assertIn('/static/js/recommendation.js', response.text)

    def test_client_calls_v1_api_without_browser_persistence_or_html_injection(self):
        source = (ROOT / "app" / "static" / "js" / "recommendation.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('fetch("/api/v1/recommendations"', source)
        self.assertIn("generate_explanation: explainToggle.checked", source)
        self.assertIn("payload.results.length !== 3", source)
        self.assertIn("textContent", source)
        self.assertIn('description_zh: "中文圖鑑敘述"', source)
        self.assertIn('analysis_text: "人格分析"', source)
        self.assertIn('"zh-Hant": "繁體中文"', source)
        self.assertIn("evidenceKindLabel(evidence.source)", source)
        self.assertIn("languageLabel(evidence.language_code)", source)
        for forbidden in (
            "innerHTML",
            "outerHTML",
            "localStorage",
            "sessionStorage",
            "document.cookie",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_pages_link_back_to_recommendation(self):
        for path in ("/pokemon", "/pokemon/1", "/admin"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('href="/">人格推薦</a>', response.text)


if __name__ == "__main__":
    unittest.main()
