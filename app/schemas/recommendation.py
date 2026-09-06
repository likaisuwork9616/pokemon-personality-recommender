from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RecommendationRequest(BaseModel):
    text: str = Field(
        min_length=2,
        max_length=2000,
        description="個性、興趣或生活習慣描述",
    )
    generate_explanation: bool = Field(
        default=False,
        description="是否呼叫外部模型產生解釋",
    )


class ScoreBreakdown(BaseModel):
    semantic: float = Field(
        ge=0,
        le=1,
        description="Dense 與中文全文檢索經 RRF 聚合後的語意相關度",
    )
    personality: float = Field(
        ge=0,
        le=1,
        description="規則式人格向量相似度",
    )
    total: float = Field(
        ge=0,
        le=1,
        description="語意與人格訊號的最終排序分數",
    )


class EvidenceResponse(BaseModel):
    """One immutable retrieval hit that can be traced back to PostgreSQL."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=r"^ev_[0-9a-f]{32}$")
    document_id: UUID
    chunk_id: UUID
    source: str = Field(min_length=1, max_length=120)
    document_kind: str = Field(min_length=1, max_length=40)
    language_code: str = Field(min_length=1, max_length=10)
    text: str = Field(min_length=1, max_length=500)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dense_rank: int | None = Field(default=None, ge=1, le=50)
    dense_score: float | None = Field(default=None, ge=-1, le=1)
    lexical_rank: int | None = Field(default=None, ge=1, le=50)
    lexical_score: float | None = Field(default=None, ge=0)
    rrf_score: float = Field(gt=0, le=2 / 61)
    matched_traits: list[str] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def require_at_least_one_branch(self) -> Self:
        dense_pair = self.dense_rank is not None and self.dense_score is not None
        lexical_pair = self.lexical_rank is not None and self.lexical_score is not None
        if (self.dense_rank is None) != (self.dense_score is None):
            raise ValueError("dense rank and score must be present together")
        if (self.lexical_rank is None) != (self.lexical_score is None):
            raise ValueError("lexical rank and score must be present together")
        if not dense_pair and not lexical_pair:
            raise ValueError("evidence must come from dense or lexical retrieval")
        return self


class PokemonSummary(BaseModel):
    id: int = Field(gt=0, description="PostgreSQL Pokémon ID")
    pokedex_number: int | str
    name_zh: str
    name_en: str
    types: str
    image_url: str | None = None


class RecommendationResult(BaseModel):
    rank: int = Field(ge=1, le=3)
    pokemon: PokemonSummary
    scores: ScoreBreakdown
    evidence: list[EvidenceResponse] = Field(min_length=1, max_length=3)
    explanation: str | None = None


class RecommendationResponse(BaseModel):
    algorithm_version: str = "pgvector-fts-rrf-v1"
    results: list[RecommendationResult] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def require_exact_unique_top_three(self) -> Self:
        if [result.rank for result in self.results] != [1, 2, 3]:
            raise ValueError("recommendation ranks must be exactly 1, 2, 3")
        pokemon_ids = [result.pokemon.id for result in self.results]
        if len(set(pokemon_ids)) != 3:
            raise ValueError("recommendations must contain three unique Pokémon")
        return self
