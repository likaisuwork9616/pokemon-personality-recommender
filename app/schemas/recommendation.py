from pydantic import BaseModel, Field

class RecommendationRequest(BaseModel):
    text: str = Field(min_length=2, max_length=2000, description="個性、興趣或生活習慣描述")
    generate_explanation: bool = Field(default=False, description="是否呼叫外部模型產生解釋")

class ScoreBreakdown(BaseModel):
    semantic: float = Field(ge=0, le=1)
    personality: float = Field(ge=0, le=1)
    total: float = Field(ge=0, le=1)

class EvidenceResponse(BaseModel):
    source: str
    text: str
    matched_traits: list[str] = Field(default_factory=list)

class PokemonSummary(BaseModel):
    pokedex_number: int | str
    name_zh: str
    name_en: str
    types: str
    image_url: str | None = None

class RecommendationResult(BaseModel):
    rank: int = Field(ge=1)
    pokemon: PokemonSummary
    scores: ScoreBreakdown
    evidence: list[EvidenceResponse] = Field(default_factory=list)
    explanation: str | None = None

class RecommendationResponse(BaseModel):
    algorithm_version: str = "pgvector-fts-rrf-v1"
    results: list[RecommendationResult]
