from __future__ import annotations

import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


ROOT = Path(__file__).resolve().parents[1]


class TodayPokemonWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = TestClient(create_app(lambda: object()))
        self.client = self.context.__enter__()

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)

    def test_page_exposes_accessible_twelve_sign_form_and_result_states(self):
        response = self.client.get("/today")

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-page="today-pokemon"', response.text)
        self.assertIn('id="today-form"', response.text)
        self.assertEqual(response.text.count('name="zodiac"'), 12)
        self.assertIn('href="/today" aria-current="page"', response.text)
        self.assertIn('id="today-loading"', response.text)
        self.assertIn('id="today-error"', response.text)
        self.assertIn('id="today-results"', response.text)
        self.assertIn("僅供娛樂與自我反思", response.text)
        self.assertIn("/static/js/today_pokemon.js?v=20260929-2", response.text)
        self.assertIn("/static/css/app.css?v=20260929-4", response.text)

    def test_client_uses_shareable_query_without_browser_persistence_or_html_injection(self):
        source = (ROOT / "app" / "static" / "js" / "today_pokemon.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("/api/v1/today-pokemon?zodiac=", source)
        self.assertIn("new URLSearchParams(window.location.search)", source)
        self.assertIn("window.history.replaceState", source)
        self.assertIn("resultContent.replaceChildren", source)
        self.assertIn("textContent", source)
        self.assertIn("payload.selection.evidence", source)
        self.assertIn("payload.fortune.work_study", source)
        self.assertIn('image.addEventListener("error", () => image.remove()', source)
        self.assertNotIn("raw.githubusercontent.com", source)
        for forbidden in (
            "innerHTML",
            "outerHTML",
            "localStorage",
            "sessionStorage",
            "document.cookie",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_all_navigation_shells_link_to_today_page(self):
        for path in ("/", "/today", "/pokemon", "/pokemon/1", "/admin"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('href="/today"', response.text)

    def test_today_layout_has_responsive_cards_and_visible_mobile_artwork(self):
        styles = (ROOT / "app" / "static" / "css" / "app.css").read_text(
            encoding="utf-8"
        )

        self.assertIn(".today-hero {", styles)
        self.assertIn(".zodiac-grid {", styles)
        self.assertIn(".today-match-card {", styles)
        self.assertIn(".today-pokemon-image {", styles)
        self.assertIn(".fortune-grid {", styles)
        self.assertIn(".today-disclaimer {", styles)
        narrow = styles.split("@media (max-width: 34rem)", maxsplit=1)[1]
        self.assertIn(".zodiac-grid,", narrow)
        self.assertIn("grid-template-columns: 1fr 1fr", narrow)
        self.assertNotIn(".today-pokemon-image {\n    display: none", narrow)


if __name__ == "__main__":
    unittest.main()
