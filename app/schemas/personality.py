"""Public, read-only personality vocabulary schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PublicPersonalityWeightedTerm(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    term: str = Field(min_length=1, max_length=80)
    weight: float = Field(gt=0, le=5)


class PublicPersonalityTrait(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=40)
    name_zh: str = Field(min_length=1, max_length=40)
    summary: str = Field(min_length=1)
    information_style: str = Field(min_length=1)
    decision_style: str = Field(min_length=1)
    interaction_style: str = Field(min_length=1)
    action_style: str = Field(min_length=1)
    strengths: list[str] = Field(min_length=1)
    blind_spots: list[str] = Field(min_length=1)
    stress_pattern: str = Field(min_length=1)
    growth_tips: list[str] = Field(min_length=1)
    weighted_terms: list[PublicPersonalityWeightedTerm] = Field(min_length=1)
    source_urls: list[str] = Field(min_length=1)
    reviewed_at: str


class PublicPersonalityCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(gt=0)
    traits: list[PublicPersonalityTrait] = Field(min_length=16, max_length=16)
    catalog_version: str = Field(min_length=1, max_length=40)
    source: Literal["bundled"] = "bundled"
    reviewed_at: str
