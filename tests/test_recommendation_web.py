from __future__ import annotations

import unittest
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


ROOT = Path(__file__).resolve().parents[1]


class FormContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, dict[str, str | None]] = {}
        self.mbti_options: list[str] = []
        self.in_mbti_options = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"input", "textarea"} and "id" in attributes:
            self.fields[attributes["id"]] = attributes
        if tag == "datalist" and attributes.get("id") == "mbti-options":
            self.in_mbti_options = True
        if tag == "option" and self.in_mbti_options:
            self.mbti_options.append(attributes["value"])

    def handle_endtag(self, tag):
        if tag == "datalist":
            self.in_mbti_options = False


class RecommendationWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = TestClient(create_app(lambda: object()))
        self.client = self.context.__enter__()

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)

    def test_root_focuses_top_one_and_keeps_two_compact_alternatives(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="recommendation-form"', response.text)
        self.assertIn('id="personality-text"', response.text)
        self.assertNotIn('id="generate-explanation"', response.text)
        self.assertIn("<span>哪一隻寶可夢</span>", response.text)
        self.assertIn("<span>最像你？</span>", response.text)
        self.assertIn('id="recommendation-grid"', response.text)
        self.assertIn('id="recommendation-alternatives"', response.text)
        self.assertIn("最契合的人格夥伴", response.text)
        self.assertIn("其他相近結果", response.text)
        self.assertNotIn("YOUR TOP THREE", response.text)
        self.assertIn("原始文字與 query vector", response.text)
        self.assertIn("若伺服器啟用外部 AI", response.text)
        self.assertIn("文字與本次證據會送往設定的服務", response.text)
        self.assertIn('/static/js/recommendation.js?v=20260908-2', response.text)
        self.assertIn('/static/css/app.css?v=20260908-4', response.text)
        self.assertIn('id="public-trait-grid"', response.text)
        self.assertIn("MBTI 十六型人格", response.text)
        self.assertIn("同一類型的人也會有不同個性", response.text)
        self.assertNotIn("public-type-weight", response.text)
        self.assertNotIn("PostgreSQL 人格詞庫", response.text)
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
        self.assertIn("payload.catalog_version", source)
        self.assertNotIn("payload.type_profile_count", source)
        self.assertNotIn("payload.type_weight_version", source)
        self.assertNotIn("[data-example]", source)
        self.assertNotIn("dataset.example", source)
        self.assertNotIn("explainToggle", source)
        self.assertNotIn("explanationPrompt", source)
        self.assertIn("payload.results.length !== 3", source)
        self.assertIn("resultCard(payload.results[0], mbti)", source)
        self.assertIn("payload.results.slice(1).map(alternativeResultCard)", source)
        self.assertIn("textContent", source)
        self.assertIn('"AI 契合分析"', source)
        self.assertIn('gemini: "Gemini 分析"', source)
        self.assertIn("已比對個性描述", source)
        self.assertNotIn("屬性權重", source)
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

    def test_mbti_is_optional_and_has_all_sixteen_valid_choices(self):
        response = self.client.get("/")
        parser = FormContractParser()
        parser.feed(response.text)

        self.assertIn("required", parser.fields["personality-text"])
        self.assertEqual(parser.fields["personality-text"]["minlength"], "2")
        self.assertEqual(parser.fields["personality-text"]["maxlength"], "2000")
        self.assertNotIn("required", parser.fields["mbti-type"])
        self.assertEqual(parser.fields["mbti-type"]["list"], "mbti-options")
        self.assertEqual(
            set(parser.mbti_options),
            {i + s + t + j for i in "IE" for s in "SN" for t in "TF" for j in "JP"},
        )
        self.assertEqual(len(parser.mbti_options), 16)
        self.assertEqual(parser.fields["mbti-type"]["aria-describedby"], "mbti-help mbti-error")
        self.assertIn('id="mbti-error" class="mbti-error" role="alert" hidden', response.text)
        self.assertIn("A／T 不參與計分", response.text)

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
                self.assertIn('/static/css/app.css?v=20260908-4', response.text)

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
        self.assertIn(".recommendation-card.primary-result", styles)
        self.assertIn(".recommendation-alternatives-grid", styles)
        self.assertIn(".alternative-result-card", styles)

    def test_mbti_cards_include_full_profiles_and_safe_research_sources(self):
        source = (ROOT / "app" / "static" / "js" / "recommendation.js").read_text(
            encoding="utf-8"
        )
        for field in (
            "summary", "information_style", "decision_style", "interaction_style",
            "action_style", "strengths", "blind_spots", "stress_pattern", "growth_tips",
            "source_urls", "reviewed_at",
        ):
            with self.subTest(field=field):
                self.assertIn(field, source)
        self.assertIn('element("details", "public-trait-details")', source)
        self.assertIn('new URL(source)', source)
        self.assertIn('["http:", "https:"].includes(url.protocol)', source)
        self.assertIn('link.rel = "noopener noreferrer"', source)
        self.assertIn('payload.traits.length !== 16', source)

    def test_result_scores_keep_mbti_optional_and_explain_score_meaning(self):
        source = (ROOT / "app" / "static" / "js" / "recommendation.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('mbti && typeof result.scores.mbti === "number"', source)
        self.assertIn('Number.isFinite(result.scores.mbti)', source)
        self.assertIn('MBTI 輔助分（${mbti}）', source)
        self.assertIn('scoreRow("總分", result.scores.total, true)', source)
        self.assertIn('scoreRow("文字檢索分", result.scores.semantic)', source)
        self.assertIn('scoreRow("人格分數", result.scores.personality)', source)
        self.assertIn("不是 MBTI 測驗結果、機率或能力評分", source)
        self.assertNotIn("推定類型", source)

    def test_primary_and_alternative_images_remain_visible_on_narrow_screens(self):
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
        self.assertIn('pokemonImage(pokemon, "alternative-result-image")', script)
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
        self.assertIn("/static/css/app.css?v=20260908-4", response.text)
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
