from __future__ import annotations

import unittest
from datetime import datetime

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.recommendation import RetrievalUnavailableError
from app.services.today_pokemon import (
    CalendarSnapshot,
    TAIPEI,
    TodayFortune,
    TodayPokemonOutcome,
)
from app.today_pokemon_rules import ZODIAC_PROFILES, ZodiacSign


def _outcome() -> TodayPokemonOutcome:
    identity = "00000000-0000-0000-0000-000000000019"
    return TodayPokemonOutcome(
        algorithm_version="today-pokemon-v1",
        calendar=CalendarSnapshot(
            generated_at=datetime(2026, 9, 29, 14, 35, tzinfo=TAIPEI),
            valid_until=datetime(2026, 9, 29, 15, 0, tzinfo=TAIPEI),
            solar_date="2026-09-29",
            weekday_zh="星期二",
            time_hm="14:35",
            lunar_date_zh="二〇二六年八月十九",
            lunar_year_ganzhi="丙午",
            lunar_month_ganzhi="丁酉",
            lunar_day_ganzhi="丙午",
            time_ganzhi="乙未",
            time_branch="未",
            solar_term="秋分",
            season="秋",
            lunar_phase="望月前後",
        ),
        zodiac=ZODIAC_PROFILES[ZodiacSign.LEO],
        signal_trait_codes=("enthusiastic_leader", "social_charmer", "action_taker"),
        signal_trait_labels=("熱情領導", "善於交流", "果斷行動"),
        calendar_signals=("火象固定星座", "秋分・秋季金氣", "農曆望月前後", "未時・土行"),
        type_affinities=("地面", "草"),
        pokemon={
            "database_id": 25,
            "pokedex_number": 25,
            "name": "皮卡丘",
            "name_en": "Pikachu",
            "type": "電",
            "img": "https://example.test/pikachu.png",
            "pokemon_traits": ["善於交流", "果斷行動"],
            "matching_evidence": [
                {
                    "evidence_id": "ev_00000000000000000000000000000019",
                    "document_id": identity,
                    "chunk_id": identity,
                    "source": "description_zh",
                    "document_kind": "description",
                    "language_code": "zh-Hant",
                    "text": "皮卡丘會和夥伴互相交流。",
                    "content_hash": "19".zfill(64),
                    "dense_rank": 1,
                    "dense_score": 0.9,
                    "lexical_rank": None,
                    "lexical_score": None,
                    "rrf_score": 1 / 61,
                    "matched_traits": ["善於交流"],
                }
            ],
        },
        source_rank=1,
        selection_score=0.93,
        fortune=TodayFortune(
            overall=4,
            work_study=3,
            relationships=5,
            vitality=4,
            action="今天先主動完成一件最重要的小事。",
            reminder="保留一些調整空間，不需要一次做到完美。",
        ),
    )


class _Engine:
    personality_refresh_healthy = True


class _TodayService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.signs: list[ZodiacSign] = []

    def select(self, zodiac: ZodiacSign) -> TodayPokemonOutcome:
        self.signs.append(zodiac)
        if self.error:
            raise self.error
        return _outcome()

    def explain(self, _outcome: TodayPokemonOutcome) -> dict[str, object]:
        return {
            "text": "今日訊號偏向主動交流，皮卡丘重視夥伴的特質與此形成呼應。",
            "citations": ["ev_00000000000000000000000000000019"],
            "provider": "local",
            "grounded": True,
            "used_fallback": True,
        }


class TodayPokemonApiTests(unittest.TestCase):
    def test_endpoint_returns_valid_grounded_today_result_and_cache_window(self):
        service = _TodayService()
        app = create_app(
            _Engine,
            today_pokemon_service=service,
        )

        with TestClient(app) as client:
            response = client.get("/api/v1/today-pokemon?zodiac=leo")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["timezone"], "Asia/Taipei")
        self.assertEqual(body["zodiac"]["name_zh"], "獅子座")
        self.assertEqual(body["calendar"]["lunar_date_zh"], "二〇二六年八月十九")
        self.assertEqual(body["selection"]["pokemon"]["id"], 25)
        self.assertTrue(body["selection"]["explanation"]["grounded"])
        self.assertIn("僅供娛樂", body["fortune"]["disclaimer"])
        self.assertEqual(response.headers["cache-control"], "private, max-age=1470")
        self.assertEqual(service.signs, [ZodiacSign.LEO])

    def test_invalid_zodiac_is_a_sanitized_validation_error(self):
        app = create_app(_Engine, today_pokemon_service=_TodayService())

        with TestClient(app) as client:
            response = client.get("/api/v1/today-pokemon?zodiac=unknown")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "request_validation_error")
        self.assertNotIn("unknown", response.text)

    def test_retrieval_failure_maps_to_existing_503_contract(self):
        service = _TodayService(error=RetrievalUnavailableError("索引不足"))
        app = create_app(_Engine, today_pokemon_service=service)

        with TestClient(app) as client:
            response = client.get("/api/v1/today-pokemon?zodiac=pisces")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "retrieval_unavailable")

    def test_openapi_lists_today_endpoint_and_zodiac_enum(self):
        schema = create_app(_Engine, today_pokemon_service=_TodayService()).openapi()

        self.assertIn("/api/v1/today-pokemon", schema["paths"])
        self.assertEqual(
            set(schema["components"]["schemas"]["ZodiacSign"]["enum"]),
            {sign.value for sign in ZodiacSign},
        )


if __name__ == "__main__":
    unittest.main()
