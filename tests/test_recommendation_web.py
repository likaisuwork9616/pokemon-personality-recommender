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
        self.assertIn("若伺服器啟用外部 AI", response.text)
        self.assertIn("文字與本次證據會送往設定的服務", response.text)
        self.assertIn('/static/js/recommendation.js?v=20260908-1', response.text)
        self.assertIn('/static/css/app.css?v=20260908-3', response.text)
        self.assertIn('id="public-trait-grid"', response.text)
        self.assertIn("系統採用的人格特質", response.text)
        self.assertIn('id="public-type-weight-status"', response.text)
        self.assertIn("系統也有屬性參考權重", response.text)
        self.assertIn("主屬性與副屬性", response.text)
        self.assertNotIn('id="public-type-weight-grid"', response.text)
        self.assertNotIn("data-example", response.text)
        self.assertNotIn("沉著守護型", response.text)
        self.assertNotIn("好奇冒險型", response.text)
        self.assertNotIn("可靠協作型", response.text)

    def test_client_calls_v1_api_without_browser_persistence_or_html_injection(self):
        source = (ROOT / "app" / "static" / "js" / "recommendation.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('fetch("/api/v1/recommendations"', source)
        self.assertIn('fetch("/api/v1/personality/traits"', source)
        self.assertIn("generate_explanation: true", source)
        self.assertIn("publicTraitGrid.replaceChildren", source)
        self.assertIn("payload.type_profile_count", source)
        self.assertNotIn("payload.type_profiles", source)
        self.assertNotIn("[data-example]", source)
        self.assertNotIn("dataset.example", source)
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

    def test_app_pages_share_light_green_pokedex_theme(self):
        for path in ("/", "/pokemon", "/pokemon/1", "/admin"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('data-theme="pokedex"', response.text)
                self.assertIn('/static/css/app.css?v=20260908-3', response.text)

        styles = (ROOT / "app" / "static" / "css" / "app.css").read_text(
            encoding="utf-8"
        )
        body_styles = styles.split('body[data-theme="pokedex"] {', maxsplit=1)[
            1
        ].split("}", maxsplit=1)[0]
        header_styles = styles.split(".site-header {", maxsplit=1)[1].split(
            "}", maxsplit=1
        )[0]
        brand_title_styles = styles.split(".brand strong {", maxsplit=1)[1].split(
            "}", maxsplit=1
        )[0]
        brand_mark_styles = styles.split(".brand-mark {", maxsplit=1)[1].split(
            "}", maxsplit=1
        )[0]
        navigation_link_styles = styles.split(".site-nav a {", maxsplit=1)[1].split(
            "}", maxsplit=1
        )[0]
        hero_styles = styles.split(".recommendation-hero {", maxsplit=1)[1].split(
            "}", maxsplit=1
        )[0]
        dex_number_styles = styles.split(".dex-number {", maxsplit=1)[1].split(
            "}", maxsplit=1
        )[0]
        trait_title_styles = styles.rsplit(
            ".public-trait-card-heading h3 {", maxsplit=1
        )[1].split("}", maxsplit=1)[0]
        weighted_term_styles = styles.split(
            ".public-weighted-term {", maxsplit=1
        )[1].split("}", maxsplit=1)[0]
        weighted_term_text_styles = styles.split(
            ".public-weighted-term > span {", maxsplit=1
        )[1].split("}", maxsplit=1)[0]

        self.assertIn("color-scheme: light", styles)
        self.assertIn("--page-bg: #dff1dc", styles)
        self.assertIn("--pokedex-red: #d9233e", styles)
        self.assertIn('body[data-theme="pokedex"]', styles)
        self.assertIn("var(--bg)", body_styles)
        self.assertIn("var(--pokedex-red", header_styles)
        self.assertIn("min-height: 6.25rem", header_styles)
        self.assertIn("width: 3.15rem", brand_mark_styles)
        self.assertIn("font-size: 1.15rem", brand_title_styles)
        self.assertIn("font-size: 1rem", navigation_link_styles)
        self.assertIn("var(--pokedex-red", hero_styles)
        self.assertIn("var(--signal-ink)", dex_number_styles)
        self.assertIn(".site-header .button-ghost", styles)
        self.assertIn("overflow-wrap: anywhere", trait_title_styles)
        self.assertIn("max-width: 100%", weighted_term_styles)
        self.assertIn("overflow-wrap: anywhere", weighted_term_text_styles)
        self.assertIn(".public-type-weight-note", styles)
        self.assertIn(".public-type-weight-badge", styles)

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
        self.assertIn("/static/css/app.css?v=20260908-3", response.text)
        self.assertIn("/static/js/catalog.js?v=20260908-3", response.text)
        self.assertIn(".card-image::before", styles)
        self.assertIn(".card-image::after", styles)
        self.assertIn("border-radius: 50%", styles)

    def test_detail_loading_skeleton_is_hidden_after_the_request_settles(self):
        response = self.client.get("/pokemon/1")
        script = (ROOT / "app" / "static" / "js" / "catalog.js").read_text(
            encoding="utf-8"
        )
        styles = (ROOT / "app" / "static" / "css" / "app.css").read_text(
            encoding="utf-8"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="detail-loading"', response.text)
        self.assertIn('id="detail-content" hidden', response.text)
        self.assertIn("/static/js/catalog.js?v=20260908-3", response.text)
        self.assertGreaterEqual(script.count("loading.hidden = true;"), 2)
        self.assertIn("root.hidden = false;", script)
        hidden_rule = styles.split(".detail-loading[hidden] {", maxsplit=1)[1].split(
            "}", maxsplit=1
        )[0]
        self.assertIn("display: none", hidden_rule)

    def test_detail_profile_prefers_structured_traditional_chinese_metadata(self):
        script = (ROOT / "app" / "static" / "js" / "catalog.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("pokemon.ability_details", script)
        self.assertIn("abilityDetails.filter((item) => !item.is_hidden)", script)
        self.assertIn("abilityDetails.filter((item) => item.is_hidden)", script)
        self.assertIn("pokemon.habitat_detail", script)
        self.assertIn("pokemon.egg_group_details", script)
        self.assertIn("pokemon.growth_rate_detail", script)
        self.assertIn('names.join("、")', script)
        self.assertIn('"未收錄"', script)
        self.assertNotIn("item?.name_zh || item?.code", script)

    def test_public_detail_renders_only_the_traditional_chinese_pokedex_entry(self):
        script = (ROOT / "app" / "static" / "js" / "catalog.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('item.description_kind === "description"', script)
        self.assertIn('.toLowerCase() === "zh-hant"', script)
        self.assertIn('"description-meta", "中文圖鑑"', script)
        self.assertNotIn('flavor_text: "英文圖鑑"', script)
        self.assertNotIn('analysis: "人格分析"', script)
        self.assertNotIn('admin_note: "補充資料"', script)

    def test_detail_description_uses_readable_semantic_paragraphs(self):
        script = (ROOT / "app" / "static" / "js" / "catalog.js").read_text(
            encoding="utf-8"
        )
        styles = (ROOT / "app" / "static" / "css" / "app.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("item.paragraphs", script)
        self.assertIn('"description-paragraph"', script)
        self.assertNotIn('element("p", "", item.content)', script)
        self.assertIn(".description-card p + p", styles)
        self.assertIn("line-height: 1.8", styles)
        self.assertIn("line-break: strict", styles)
        self.assertIn("overflow-wrap: anywhere", styles)
        self.assertIn("node.textContent = text(content", script)
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("insertAdjacentHTML", script)


if __name__ == "__main__":
    unittest.main()
