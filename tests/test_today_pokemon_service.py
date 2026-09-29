from __future__ import annotations

import unittest
from datetime import datetime

from app.services.today_pokemon import TAIPEI, TaipeiCalendar, TodayPokemonService
from app.today_pokemon_rules import (
    ENTERTAINMENT_DISCLAIMER,
    TRAIT_LABELS,
    ZODIAC_PROFILES,
    ZodiacSign,
)


class _Engine:
    def __init__(self, totals: list[float] | None = None) -> None:
        self.calls: list[tuple[str, int]] = []
        values = totals or [0.95 - index * 0.05 for index in range(10)]
        self.results = [
            {
                "database_id": index + 1,
                "pokedex_number": index + 1,
                "name": f"寶可夢{index + 1}",
                "name_en": f"Pokemon {index + 1}",
                "type": "一般",
                "img": "",
                "scores": {"total": total, "semantic": total, "personality": total},
                "matching_evidence": [{"evidence_id": f"ev_{index + 1:032x}"}],
                "pokemon_traits": ["冷靜分析"],
            }
            for index, total in enumerate(values)
        ]

    def recommend(self, text: str, *, top_k: int):
        self.calls.append((text, top_k))
        return self.results[:top_k]


class TaipeiCalendarTests(unittest.TestCase):
    def test_known_timestamp_converts_to_lunar_calendar_and_time_branch(self):
        calendar = TaipeiCalendar(
            lambda: datetime(2026, 9, 29, 14, 35, 12, tzinfo=TAIPEI)
        )

        snapshot = calendar.snapshot()

        self.assertEqual(snapshot.solar_date, "2026-09-29")
        self.assertEqual(snapshot.weekday_zh, "星期二")
        self.assertEqual(snapshot.time_hm, "14:35")
        self.assertEqual(snapshot.lunar_date_zh, "二〇二六年八月十九")
        self.assertEqual(snapshot.lunar_year_ganzhi, "丙午")
        self.assertEqual(snapshot.time_branch, "未")
        self.assertEqual(snapshot.solar_term, "秋分")
        self.assertEqual(snapshot.season, "秋")
        self.assertEqual(snapshot.lunar_phase, "望月前後")
        self.assertEqual(snapshot.valid_until.isoformat(), "2026-09-29T15:00:00+08:00")

    def test_civil_midnight_splits_the_traditional_zi_period(self):
        before_midnight = TaipeiCalendar(
            lambda: datetime(2026, 9, 29, 23, 30, tzinfo=TAIPEI)
        ).snapshot()
        after_midnight = TaipeiCalendar(
            lambda: datetime(2026, 9, 30, 0, 30, tzinfo=TAIPEI)
        ).snapshot()

        self.assertEqual(before_midnight.time_branch, "子")
        self.assertEqual(after_midnight.time_branch, "子")
        self.assertEqual(before_midnight.valid_until.isoformat(), "2026-09-30T00:00:00+08:00")
        self.assertEqual(after_midnight.valid_until.isoformat(), "2026-09-30T01:00:00+08:00")
        self.assertNotEqual(before_midnight.solar_date, after_midnight.solar_date)


class TodayPokemonServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 29, 14, 35, tzinfo=TAIPEI)
        self.engine = _Engine()
        self.service = TodayPokemonService(
            self.engine,
            calendar=TaipeiCalendar(lambda: self.now),
        )

    def test_rules_cover_all_twelve_western_zodiac_signs(self):
        self.assertEqual(set(ZODIAC_PROFILES), set(ZodiacSign))
        self.assertEqual(len(ZODIAC_PROFILES), 12)
        self.assertTrue(
            all(profile.trait_codes for profile in ZODIAC_PROFILES.values())
        )

    def test_same_sign_and_time_block_are_reproducible(self):
        first = self.service.select(ZodiacSign.LEO)
        second = self.service.select("leo")

        self.assertEqual(first.pokemon["database_id"], second.pokemon["database_id"])
        self.assertEqual(first.selection_score, second.selection_score)
        self.assertEqual(first.fortune, second.fortune)
        self.assertEqual(self.engine.calls[0][1], 10)
        self.assertIn("獅子座", self.engine.calls[0][0])
        self.assertIn("秋分未時", self.engine.calls[0][0])

    def test_relevance_keeps_a_clear_top_candidate_ahead_of_daily_rotation(self):
        engine = _Engine([1.0, *([0.0] * 9)])
        service = TodayPokemonService(
            engine,
            calendar=TaipeiCalendar(lambda: self.now),
        )

        outcome = service.select(ZodiacSign.PISCES)

        self.assertEqual(outcome.pokemon["database_id"], 1)
        self.assertEqual(outcome.source_rank, 1)

    def test_fortune_is_bounded_and_always_carries_entertainment_disclaimer(self):
        fortune = self.service.select(ZodiacSign.AQUARIUS).fortune

        for score in (
            fortune.overall,
            fortune.work_study,
            fortune.relationships,
            fortune.vitality,
        ):
            self.assertIn(score, range(1, 6))
        self.assertEqual(fortune.disclaimer, ENTERTAINMENT_DISCLAIMER)
        self.assertTrue(fortune.action)
        self.assertTrue(fortune.reminder)

    def test_service_rejects_rules_when_an_active_trait_code_is_missing(self):
        active = list(TRAIT_LABELS)
        active.remove("systems_thinker")

        with self.assertRaisesRegex(RuntimeError, "systems_thinker"):
            TodayPokemonService(self.engine, active_trait_codes=active)


if __name__ == "__main__":
    unittest.main()
