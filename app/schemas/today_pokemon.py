"""Public response contract for the Today Pokémon experience."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.recommendation import EvidenceResponse, ExplanationResponse, PokemonSummary
from app.today_pokemon_rules import ZodiacSign


class TodayCalendarResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    solar_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    weekday_zh: str
    time_hm: str = Field(pattern=r"^\d{2}:\d{2}$")
    lunar_date_zh: str
    lunar_year_ganzhi: str
    lunar_month_ganzhi: str
    lunar_day_ganzhi: str
    time_ganzhi: str
    time_branch: str = Field(pattern=r"^[子丑寅卯辰巳午未申酉戌亥]$")
    solar_term: str
    season: Literal["春", "夏", "秋", "冬"]
    lunar_phase: Literal["月初", "漸盈", "望月前後", "漸虧"]


class TodayZodiacResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ZodiacSign
    name_zh: str
    symbol: str
    date_range: str
    element: Literal["火", "土", "風", "水"]
    modality: Literal["開創", "固定", "變動"]
    traits: list[str] = Field(min_length=3, max_length=10)


class TodayFortuneResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall: int = Field(ge=1, le=5)
    work_study: int = Field(ge=1, le=5)
    relationships: int = Field(ge=1, le=5)
    vitality: int = Field(ge=1, le=5)
    action: str = Field(min_length=10, max_length=120)
    reminder: str = Field(min_length=10, max_length=120)
    disclaimer: str = Field(min_length=10, max_length=120)


class TodayPokemonSelectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pokemon: PokemonSummary
    source_rank: int = Field(ge=1, le=10)
    selection_score: float = Field(
        ge=0,
        le=1,
        description="相關性與每日穩定輪替的選擇分數，不代表機率",
    )
    pokemon_traits: list[str] = Field(default_factory=list, max_length=3)
    type_affinities: list[str] = Field(min_length=1, max_length=3)
    evidence: list[EvidenceResponse] = Field(min_length=1, max_length=3)
    explanation: ExplanationResponse

    @model_validator(mode="after")
    def explanation_must_cite_own_evidence(self) -> Self:
        allowed = {item.evidence_id for item in self.evidence}
        if not set(self.explanation.citations).issubset(allowed):
            raise ValueError("today explanation cited evidence from another Pokémon")
        return self


class TodayPokemonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithm_version: str
    timezone: Literal["Asia/Taipei"] = "Asia/Taipei"
    generated_at: datetime
    valid_until: datetime
    zodiac: TodayZodiacResponse
    calendar: TodayCalendarResponse
    calendar_signals: list[str] = Field(min_length=4, max_length=4)
    selection: TodayPokemonSelectionResponse
    fortune: TodayFortuneResponse

    @model_validator(mode="after")
    def validity_window_must_move_forward(self) -> Self:
        if self.valid_until <= self.generated_at:
            raise ValueError("today Pokémon validity window must move forward")
        return self
