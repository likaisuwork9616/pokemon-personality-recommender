"""Validated contracts for the collaborative evaluation workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


CaseStatus = Literal["draft", "active", "retired"]
RelevanceGrade = Annotated[int, Field(ge=0, le=3)]


class EvaluationCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_key: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    query: str = Field(min_length=4, max_length=2_000)
    segment: str = Field(default="general", min_length=1, max_length=80)
    dataset_version: str = Field(min_length=1, max_length=40)
    pokemon_ids: list[int] = Field(min_length=2, max_length=30)

    @field_validator("pokemon_ids")
    @classmethod
    def unique_candidates(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("pokemon_ids must be positive")
        if len(set(values)) != len(values):
            raise ValueError("pokemon_ids must be unique")
        return values


class EvaluationJudgmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    pokemon_id: int = Field(gt=0)
    grade: RelevanceGrade
    note: str | None = Field(default=None, max_length=500)


class EvaluationJudgmentBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    judgments: list[EvaluationJudgmentInput] = Field(min_length=1, max_length=30)

    @field_validator("judgments")
    @classmethod
    def unique_pokemon(cls, values: list[EvaluationJudgmentInput]) -> list[EvaluationJudgmentInput]:
        pokemon_ids = [value.pokemon_id for value in values]
        if len(set(pokemon_ids)) != len(pokemon_ids):
            raise ValueError("each pokemon_id may appear only once")
        return values


class EvaluationCaseStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CaseStatus


class EvaluationAnnotationResponse(BaseModel):
    annotator: str
    grade: RelevanceGrade
    note: str | None = None
    updated_at: datetime


class EvaluationAdjudicationResponse(BaseModel):
    adjudicator: str
    grade: RelevanceGrade
    note: str | None = None
    updated_at: datetime


class EvaluationCandidateResponse(BaseModel):
    pokemon_id: int
    pokedex_number: int
    name_zh: str
    display_order: int
    annotations: list[EvaluationAnnotationResponse]
    adjudication: EvaluationAdjudicationResponse | None = None


class EvaluationCaseResponse(BaseModel):
    id: UUID
    case_key: str
    query: str
    segment: str
    dataset_version: str
    status: CaseStatus
    created_by: str
    created_at: datetime
    updated_at: datetime
    candidates: list[EvaluationCandidateResponse]


class EvaluationCasePage(BaseModel):
    items: list[EvaluationCaseResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class EvaluationDatasetExport(BaseModel):
    case_count: int = Field(ge=0)
    cases: list[dict[str, object]]
