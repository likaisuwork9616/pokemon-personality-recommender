"""Deterministic zodiac, calendar, and Pokédex matching for Today Pokémon."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

from lunar_python import Solar

from app.today_pokemon_rules import (
    ACTION_TEMPLATES,
    ELEMENT_TRAITS,
    ENTERTAINMENT_DISCLAIMER,
    FACET_TRAITS,
    LUNAR_PHASE_RULES,
    MODALITY_TRAITS,
    REMINDER_TEMPLATES,
    SEASON_RULES,
    TIME_BRANCH_RULES,
    TODAY_POKEMON_ALGORITHM_VERSION,
    TRAIT_LABELS,
    TRAIT_QUERY_TERMS,
    ZODIAC_PROFILES,
    ZodiacProfile,
    ZodiacSign,
    season_for_solar_term,
    validate_today_pokemon_rules,
)


TAIPEI = ZoneInfo("Asia/Taipei")
WEEKDAYS_ZH = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


@dataclass(frozen=True)
class CalendarSnapshot:
    generated_at: datetime
    valid_until: datetime
    solar_date: str
    weekday_zh: str
    time_hm: str
    lunar_date_zh: str
    lunar_year_ganzhi: str
    lunar_month_ganzhi: str
    lunar_day_ganzhi: str
    time_ganzhi: str
    time_branch: str
    solar_term: str
    season: str
    lunar_phase: str


@dataclass(frozen=True)
class TodayFortune:
    overall: int
    work_study: int
    relationships: int
    vitality: int
    action: str
    reminder: str
    disclaimer: str = ENTERTAINMENT_DISCLAIMER


@dataclass(frozen=True)
class TodayPokemonOutcome:
    algorithm_version: str
    calendar: CalendarSnapshot
    zodiac: ZodiacProfile
    signal_trait_codes: tuple[str, ...]
    signal_trait_labels: tuple[str, ...]
    calendar_signals: tuple[str, ...]
    type_affinities: tuple[str, ...]
    pokemon: Mapping[str, Any]
    source_rank: int
    selection_score: float
    fortune: TodayFortune


class TaipeiCalendar:
    """Capture one immutable Taipei civil-time and lunar-calendar snapshot."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(TAIPEI))

    def snapshot(self) -> CalendarSnapshot:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=TAIPEI)
        local = value.astimezone(TAIPEI).replace(microsecond=0)
        solar = Solar.fromYmdHms(
            local.year,
            local.month,
            local.day,
            local.hour,
            local.minute,
            local.second,
        )
        lunar = solar.getLunar()
        jie_qi = lunar.getCurrentJieQi() or lunar.getPrevJieQi()
        solar_term = str(jie_qi.getName())
        lunar_day = int(lunar.getDay())
        phase = self._lunar_phase(lunar_day)
        valid_until = self._valid_until(local)
        return CalendarSnapshot(
            generated_at=local,
            valid_until=valid_until,
            solar_date=local.date().isoformat(),
            weekday_zh=WEEKDAYS_ZH[local.weekday()],
            time_hm=local.strftime("%H:%M"),
            lunar_date_zh=(
                f"{lunar.getYearInChinese()}年"
                f"{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}"
            ),
            lunar_year_ganzhi=str(lunar.getYearInGanZhi()),
            lunar_month_ganzhi=str(lunar.getMonthInGanZhi()),
            lunar_day_ganzhi=str(lunar.getDayInGanZhi()),
            time_ganzhi=str(lunar.getTimeInGanZhi()),
            time_branch=str(lunar.getTimeZhi()),
            solar_term=solar_term,
            season=season_for_solar_term(solar_term),
            lunar_phase=phase,
        )

    @staticmethod
    def _lunar_phase(day: int) -> str:
        if 1 <= day <= 7:
            return "月初"
        if day <= 14:
            return "漸盈"
        if day <= 21:
            return "望月前後"
        return "漸虧"

    @staticmethod
    def _valid_until(local: datetime) -> datetime:
        if local.hour == 23:
            return (local + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        if local.hour == 0:
            return local.replace(hour=1, minute=0, second=0, microsecond=0)
        next_hour = ((local.hour - 1) // 2) * 2 + 3
        return local.replace(hour=next_hour, minute=0, second=0, microsecond=0)


class TodayPokemonService:
    """Select one relevant Pokémon and entertainment-only fortune per time block."""

    def __init__(
        self,
        engine: Any,
        *,
        calendar: TaipeiCalendar | None = None,
        active_trait_codes: Sequence[str] = tuple(TRAIT_LABELS),
    ) -> None:
        validate_today_pokemon_rules(frozenset(active_trait_codes))
        self.engine = engine
        self.calendar = calendar or TaipeiCalendar()

    def select(self, zodiac: ZodiacSign | str) -> TodayPokemonOutcome:
        sign = zodiac if isinstance(zodiac, ZodiacSign) else ZodiacSign(str(zodiac))
        snapshot = self.calendar.snapshot()
        profile = ZODIAC_PROFILES[sign]
        trait_codes, calendar_signals, type_affinities = self._signals(profile, snapshot)
        query = self._query_text(profile, snapshot, trait_codes, type_affinities)
        candidates = list(self.engine.recommend(query, top_k=10))
        if not candidates:
            raise ValueError("today Pokémon selection requires at least one candidate")
        selected, source_rank, score = self._select_candidate(
            candidates,
            sign=sign,
            snapshot=snapshot,
        )
        fortune = self._fortune(
            sign=sign,
            snapshot=snapshot,
            trait_codes=trait_codes,
        )
        return TodayPokemonOutcome(
            algorithm_version=TODAY_POKEMON_ALGORITHM_VERSION,
            calendar=snapshot,
            zodiac=profile,
            signal_trait_codes=trait_codes,
            signal_trait_labels=tuple(TRAIT_LABELS[code] for code in trait_codes),
            calendar_signals=calendar_signals,
            type_affinities=type_affinities,
            pokemon=selected,
            source_rank=source_rank,
            selection_score=round(score, 8),
            fortune=fortune,
        )

    @staticmethod
    def _signals(
        profile: ZodiacProfile,
        snapshot: CalendarSnapshot,
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        branch_element, branch_trait, type_affinities = TIME_BRANCH_RULES[
            snapshot.time_branch
        ]
        season_element, season_trait = SEASON_RULES[snapshot.season]
        ordered = (
            *profile.trait_codes,
            *ELEMENT_TRAITS[profile.element],
            *MODALITY_TRAITS[profile.modality],
            branch_trait,
            LUNAR_PHASE_RULES[snapshot.lunar_phase],
            season_trait,
        )
        unique_traits = tuple(dict.fromkeys(ordered))
        signals = (
            f"{profile.element}象{profile.modality}星座",
            f"{snapshot.solar_term}・{snapshot.season}季{season_element}氣",
            f"農曆{snapshot.lunar_phase}",
            f"{snapshot.time_branch}時・{branch_element}行",
        )
        return unique_traits, signals, type_affinities

    @staticmethod
    def _query_text(
        profile: ZodiacProfile,
        snapshot: CalendarSnapshot,
        trait_codes: Sequence[str],
        type_affinities: Sequence[str],
    ) -> str:
        terms = [term for code in trait_codes for term in TRAIT_QUERY_TERMS[code]]
        return " ".join(
            (
                f"今日{profile.name_zh}代表寶可夢",
                f"國曆{snapshot.solar_date}",
                f"農曆{snapshot.lunar_date_zh}",
                f"{snapshot.solar_term}{snapshot.time_branch}時",
                *terms,
                *type_affinities,
            )
        )

    @classmethod
    def _select_candidate(
        cls,
        candidates: Sequence[Mapping[str, Any]],
        *,
        sign: ZodiacSign,
        snapshot: CalendarSnapshot,
    ) -> tuple[Mapping[str, Any], int, float]:
        totals = [float(item.get("scores", {}).get("total", 0.0)) for item in candidates]
        low, high = min(totals), max(totals)
        denominator = high - low
        scored: list[tuple[float, float, int, Mapping[str, Any]]] = []
        count = len(candidates)
        for index, (candidate, total) in enumerate(zip(candidates, totals, strict=True)):
            relevance = (
                (total - low) / denominator
                if denominator > 1e-12
                else 1.0 - (index / max(1, count - 1))
            )
            pokemon_id = int(candidate["database_id"])
            daily = cls._unit_hash(
                TODAY_POKEMON_ALGORITHM_VERSION,
                snapshot.solar_date,
                snapshot.time_branch,
                sign.value,
                str(pokemon_id),
            )
            selection_score = 0.9 * relevance + 0.1 * daily
            scored.append((selection_score, total, -pokemon_id, candidate))
        selection_score, _total, _negative_id, selected = max(scored)
        source_rank = candidates.index(selected) + 1
        return selected, source_rank, selection_score

    @classmethod
    def _fortune(
        cls,
        *,
        sign: ZodiacSign,
        snapshot: CalendarSnapshot,
        trait_codes: Sequence[str],
    ) -> TodayFortune:
        trait_set = set(trait_codes)
        scores: dict[str, int] = {}
        for facet in ("work_study", "relationships", "vitality"):
            hashed = cls._unit_hash(
                TODAY_POKEMON_ALGORITHM_VERSION,
                snapshot.solar_date,
                snapshot.time_branch,
                sign.value,
                facet,
            )
            daily_delta = (-2, -1, 0, 1, 2)[min(4, int(hashed * 5))]
            resonance = 1 if len(trait_set & FACET_TRAITS[facet]) >= 2 else 0
            scores[facet] = max(1, min(5, 3 + daily_delta + resonance))
        overall_delta = (-1, 0, 1)[min(2, int(cls._unit_hash(
            TODAY_POKEMON_ALGORITHM_VERSION,
            snapshot.solar_date,
            snapshot.time_branch,
            sign.value,
            "overall",
        ) * 3))]
        scores["overall"] = max(
            1,
            min(5, round(sum(scores.values()) / len(scores)) + overall_delta),
        )
        ordered_facets = ("overall", "work_study", "relationships", "vitality")
        highest = max(ordered_facets, key=lambda facet: (scores[facet], -ordered_facets.index(facet)))
        lowest = min(ordered_facets, key=lambda facet: (scores[facet], ordered_facets.index(facet)))
        return TodayFortune(
            overall=scores["overall"],
            work_study=scores["work_study"],
            relationships=scores["relationships"],
            vitality=scores["vitality"],
            action=ACTION_TEMPLATES[highest],
            reminder=REMINDER_TEMPLATES[lowest],
        )

    @staticmethod
    def _unit_hash(*parts: str) -> float:
        digest = sha256("|".join(parts).encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / float(2**64 - 1)
