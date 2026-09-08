"""Public, read-only personality vocabulary schemas."""

from pydantic import BaseModel, ConfigDict, Field


class PublicPersonalityWeightedTerm(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    term: str = Field(min_length=1, max_length=80)
    weight: float = Field(gt=0, le=5)


class PublicPersonalityTrait(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=40)
    name_zh: str = Field(min_length=1, max_length=40)
    weighted_terms: list[PublicPersonalityWeightedTerm] = Field(min_length=1)


class PublicPersonalityCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(gt=0)
    traits: list[PublicPersonalityTrait] = Field(min_length=16, max_length=16)
    type_weight_version: str = Field(min_length=1, max_length=40)
    type_profile_count: int = Field(gt=0, le=18)
