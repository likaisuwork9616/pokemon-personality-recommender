from __future__ import annotations

import unittest

from app.services.rag import GroundedExplanationService, LLMExplanationBundle


def _result() -> dict[str, object]:
    return {
        "rank": 1,
        "database_id": 25,
        "pokedex_number": 25,
        "name": "皮卡丘",
        "name_en": "Pikachu",
        "type": "電",
        "category": "鼠寶可夢",
        "desc": "皮卡丘會和夥伴互相交流，也會主動保護同伴。",
        "analysis_text": "牠重視交流，也願意在需要時採取行動。",
        "pokemon_traits": ["善於交流", "果斷行動"],
        "type_weight_signals": {},
        "matching_evidence": [
            {
                "evidence_id": "ev_00000000000000000000000000000019",
                "source": "description_zh",
                "language_code": "zh-Hant",
                "text": "皮卡丘會和夥伴互相交流，也會主動保護同伴。",
                "matched_traits": ["善於交流"],
            }
        ],
    }


CONTEXT = {
    "zodiac": {
        "code": "leo",
        "name_zh": "獅子座",
        "element": "火",
        "modality": "固定",
        "traits": ["熱情領導", "善於交流", "果斷行動"],
    },
    "calendar": {
        "solar_date": "2026-09-29",
        "lunar_date_zh": "二〇二六年八月十九",
        "solar_term": "秋分",
        "time_branch": "未",
        "signals": ["火象固定星座", "秋分・秋季金氣", "農曆望月前後", "未時・土行"],
    },
}


class _Provider:
    name = "gemini"

    def __init__(self, *, citation: str) -> None:
        self.citation = citation
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> LLMExplanationBundle:
        self.prompts.append(prompt)
        return LLMExplanationBundle.model_validate(
            {
                "explanations": [
                    {
                        "pokemon_id": 25,
                        "text": "今日訊號偏向主動交流，而皮卡丘也重視夥伴並願意行動，兩者形成呼應。",
                        "citations": [self.citation],
                    }
                ]
            }
        )


class TodayPokemonRagTests(unittest.TestCase):
    def test_local_explanation_is_grounded_and_uses_today_wording(self):
        explanation = GroundedExplanationService().explain_today(CONTEXT, _result())

        self.assertEqual(explanation.provider, "local")
        self.assertTrue(explanation.used_fallback)
        self.assertIn("今天的獅子座", explanation.text)
        self.assertNotIn("你的描述", explanation.text)
        self.assertEqual(
            explanation.citations,
            ("ev_00000000000000000000000000000019",),
        )

    def test_provider_receives_untrusted_entertainment_context(self):
        provider = _Provider(citation="ev_00000000000000000000000000000019")

        explanation = GroundedExplanationService(provider).explain_today(
            CONTEXT,
            _result(),
        )

        self.assertEqual(explanation.provider, "gemini")
        self.assertIn('"mode":"today_pokemon"', provider.prompts[0])
        self.assertIn('"entertainment_only":true', provider.prompts[0])
        self.assertIn("BEGIN_UNTRUSTED_DATA", provider.prompts[0])

    def test_invalid_provider_citation_falls_back_to_local(self):
        provider = _Provider(citation="ev_ffffffffffffffffffffffffffffffff")

        explanation = GroundedExplanationService(provider).explain_today(
            CONTEXT,
            _result(),
        )

        self.assertEqual(explanation.provider, "local")
        self.assertTrue(explanation.used_fallback)


if __name__ == "__main__":
    unittest.main()
