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
        self.assertNotIn('id="generate-explanation"', response.text)
        self.assertIn("<span>哪一隻寶可夢</span>", response.text)
        self.assertIn("<span>最像你？</span>", response.text)
        self.assertIn('id="recommendation-grid"', response.text)
        self.assertIn("原始文字與 query vector", response.text)
        self.assertIn('/static/js/recommendation.js?v=20260907-4', response.text)
        self.assertIn('/static/css/app.css?v=20260907-4', response.text)

    def test_client_calls_v1_api_without_browser_persistence_or_html_injection(self):
        source = (ROOT / "app" / "static" / "js" / "recommendation.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('fetch("/api/v1/recommendations"', source)
        self.assertIn("generate_explanation: true", source)
        self.assertNotIn("explainToggle", source)
        self.assertNotIn("explanationPrompt", source)
        self.assertIn("payload.results.length !== 3", source)
        self.assertIn("textContent", source)
        self.assertIn('"AI 契合分析"', source)
        self.assertIn('gemini: "Gemini 分析"', source)
        self.assertIn("已融合人格訊號與", source)
        self.assertNotIn("evidence.text", source)
        self.assertNotIn("Evidence ID", source)
        self.assertNotIn("Document ID", source)
        self.assertNotIn("Chunk ID", source)
        self.assertNotIn("RRF", source)
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

    def test_top_three_images_remain_visible_on_narrow_screens(self):
        script = (ROOT / "app" / "static" / "js" / "recommendation.js").read_text(
            encoding="utf-8"
        )
        styles = (ROOT / "app" / "static" / "css" / "app.css").read_text(
            encoding="utf-8"
        )
        narrow_styles = styles.split("@media (max-width: 34rem)", maxsplit=1)[1]

        self.assertIn("safeImageUrl(pokemon.image_url)", script)
        self.assertIn("officialArtworkUrl(pokemon.pokedex_number)", script)
        self.assertIn("imageShell.append(image)", script)
        self.assertIn('image.referrerPolicy = "no-referrer"', script)
        self.assertIn("image.src = fallbackImageUrl", script)
        self.assertIn("grid-area: 1 / 1", styles)
        self.assertIn(".hero-copy h1 span", styles)
        self.assertIn("white-space: nowrap", styles)
        self.assertIn("grid-template-columns: auto minmax(0, 1fr) 4.2rem", narrow_styles)
        self.assertIn(".recommendation-image {\n    display: grid", narrow_styles)
        self.assertNotIn(".recommendation-image {\n    display: none", narrow_styles)

    def test_catalog_uses_css_pokeball_artwork_backdrop(self):
        response = self.client.get("/pokemon")
        styles = (ROOT / "app" / "static" / "css" / "app.css").read_text(
            encoding="utf-8"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("/static/css/app.css?v=20260907-5", response.text)
        self.assertIn("/static/js/catalog.js?v=20260907-5", response.text)
        self.assertIn(".card-image::before", styles)
        self.assertIn(".card-image::after", styles)
        self.assertIn("border-radius: 50%", styles)


if __name__ == "__main__":
    unittest.main()
