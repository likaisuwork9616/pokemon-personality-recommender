"""Validated public contracts for the single-administrator API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.schemas.catalog import PokemonDetail


TypeCode = Annotated[
    str,
    Field(min_length=1, max_length=40, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$"),
]

NON_NULL_UPDATE_FIELDS = frozenset(
    {
        "pokedex_number",
        "form_key",
        "name_zh",
        "name_en",
        "generation",
        "abilities",
        "egg_groups",
        "is_legendary",
        "is_mythical",
        "is_baby",
        "is_outlier",
        "lof_outlier",
        "type_codes",
    }
)


def _validate_child_uniqueness(
    type_codes: list[str] | None,
    descriptions: list[AdminDescriptionInput] | None,
    images: list[AdminImageInput] | None,
) -> None:
    if type_codes is not None:
        normalized_types = [value.casefold() for value in type_codes]
        if len(set(normalized_types)) != len(normalized_types):
            raise ValueError("type_codes must be unique")
    if descriptions is not None:
        description_keys = [
            (
                item.language_code,
                item.description_kind,
                item.source_key.removeprefix("csv:"),
            )
            for item in descriptions
        ]
        if len(set(description_keys)) != len(description_keys):
            raise ValueError("description source tuples must be unique")
        primary_groups = [
            (item.language_code, item.description_kind)
            for item in descriptions
            if item.is_primary
        ]
        if len(set(primary_groups)) != len(primary_groups):
            raise ValueError("only one primary description is allowed per group")
    if images is not None:
        image_kinds = [item.image_kind for item in images]
        if len(set(image_kinds)) != len(image_kinds):
            raise ValueError("image kinds must be unique")
        if sum(item.is_primary for item in images) > 1:
            raise ValueError("only one primary image is allowed")


class AdminLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=256)


class AdminSessionResponse(BaseModel):
    authenticated: Literal[True] = True
    csrf_token: str = Field(min_length=32)
    expires_at: int


class AdminDescriptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    language_code: str = Field(min_length=1, max_length=10)
    description_kind: Literal[
        "description",
        "flavor_text",
        "analysis",
        "admin_note",
    ]
    source_key: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=20_000)
    is_primary: bool = False


class AdminImageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    image_kind: Literal["artwork", "sprite"]
    image_url: HttpUrl
    is_primary: bool = False


class AdminStatsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hp: int = Field(ge=0, le=999)
    attack: int = Field(ge=0, le=999)
    defense: int = Field(ge=0, le=999)
    sp_attack: int = Field(ge=0, le=999)
    sp_defense: int = Field(ge=0, le=999)
    speed: int = Field(ge=0, le=999)
    base_stat_total: int = Field(ge=0, le=5994)

    @model_validator(mode="after")
    def total_matches_components(self) -> Self:
        expected = (
            self.hp
            + self.attack
            + self.defense
            + self.sp_attack
            + self.sp_defense
            + self.speed
        )
        if self.base_stat_total != expected:
            raise ValueError("base_stat_total must equal the six component stats")
        return self


class AdminPokemonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    pokedex_number: int = Field(gt=0)
    form_key: str = Field(default="default", min_length=1, max_length=80)
    name_zh: str = Field(min_length=1, max_length=120)
    name_en: str = Field(min_length=1, max_length=120)
    category_zh: str | None = Field(default=None, max_length=160)
    genus: str | None = Field(default=None, max_length=160)
    generation: int = Field(ge=1, le=9)
    habitat: str | None = Field(default=None, max_length=120)
    color: str | None = Field(default=None, max_length=80)
    shape: str | None = Field(default=None, max_length=120)
    growth_rate: str | None = Field(default=None, max_length=40)
    abilities: str = Field(default="", max_length=2000)
    hidden_ability: str | None = Field(default=None, max_length=120)
    egg_groups: str = Field(default="", max_length=1000)
    height_m: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    capture_rate: int | None = Field(default=None, ge=0, le=255)
    is_legendary: bool = False
    is_mythical: bool = False
    is_baby: bool = False
    is_outlier: Literal[-1, 1] = 1
    lof_outlier: Literal[-1, 1] = 1
    type_codes: list[TypeCode] = Field(min_length=1, max_length=2)
    stats: AdminStatsInput | None = None
    descriptions: list[AdminDescriptionInput] = Field(
        default_factory=list,
        max_length=20,
    )
    images: list[AdminImageInput] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def validate_child_uniqueness(self) -> Self:
        _validate_child_uniqueness(
            self.type_codes,
            self.descriptions,
            self.images,
        )
        return self


class AdminPokemonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    pokedex_number: int | None = Field(default=None, gt=0)
    form_key: str | None = Field(default=None, min_length=1, max_length=80)
    name_zh: str | None = Field(default=None, min_length=1, max_length=120)
    name_en: str | None = Field(default=None, min_length=1, max_length=120)
    category_zh: str | None = Field(default=None, max_length=160)
    genus: str | None = Field(default=None, max_length=160)
    generation: int | None = Field(default=None, ge=1, le=9)
    habitat: str | None = Field(default=None, max_length=120)
    color: str | None = Field(default=None, max_length=80)
    shape: str | None = Field(default=None, max_length=120)
    growth_rate: str | None = Field(default=None, max_length=40)
    abilities: str | None = Field(default=None, max_length=2000)
    hidden_ability: str | None = Field(default=None, max_length=120)
    egg_groups: str | None = Field(default=None, max_length=1000)
    height_m: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    capture_rate: int | None = Field(default=None, ge=0, le=255)
    is_legendary: bool | None = None
    is_mythical: bool | None = None
    is_baby: bool | None = None
    is_outlier: Literal[-1, 1] | None = None
    lof_outlier: Literal[-1, 1] | None = None
    type_codes: list[TypeCode] | None = Field(
        default=None,
        min_length=1,
        max_length=2,
    )
    stats: AdminStatsInput | None = None
    descriptions: list[AdminDescriptionInput] | None = Field(default=None, max_length=20)
    images: list[AdminImageInput] | None = Field(default=None, max_length=2)

    @model_validator(mode="after")
    def validate_update(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        null_fields = sorted(
            field
            for field in self.model_fields_set & NON_NULL_UPDATE_FIELDS
            if getattr(self, field) is None
        )
        if null_fields:
            raise ValueError(f"fields cannot be null: {', '.join(null_fields)}")
        _validate_child_uniqueness(
            self.type_codes if "type_codes" in self.model_fields_set else None,
            self.descriptions if "descriptions" in self.model_fields_set else None,
            self.images if "images" in self.model_fields_set else None,
        )
        return self


class AdminPokemonSummary(BaseModel):
    id: int
    pokedex_number: int
    form_key: str
    name_zh: str
    name_en: str
    generation: int
    is_active: bool


class AdminPokemonPage(BaseModel):
    items: list[AdminPokemonSummary]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class AdminPokemonDetail(PokemonDetail):
    is_active: bool


IndexStatus = Literal["ready", "stale", "failed", "unindexed"]


class AdminIndexSourceStatus(BaseModel):
    source_key: str
    status: IndexStatus
    current_document_id: UUID | None = None
    current_version: int | None = Field(default=None, ge=1)
    staged_document_id: UUID | None = None
    staged_version: int | None = Field(default=None, ge=1)
    total_chunks: int = Field(ge=0)
    ready_chunks: int = Field(ge=0)
    last_error: str | None = None


class AdminIndexStatus(BaseModel):
    pokemon_id: int
    status: IndexStatus
    sources: list[AdminIndexSourceStatus]


class AdminReindexResponse(BaseModel):
    pokemon_id: int
    embedding_model_id: int
    discovered: int = Field(ge=0)
    embedded: int = Field(ge=0)
    failed: int = Field(ge=0)
    index: AdminIndexStatus


ReindexJobStatus = Literal["queued", "running", "succeeded", "failed"]


class AdminReindexJobResponse(BaseModel):
    id: UUID
    pokemon_id: int
    status: ReindexJobStatus
    progress_current: int = Field(ge=0)
    progress_total: int = Field(ge=0)
    embedded: int = Field(ge=0)
    failed: int = Field(ge=0)
    message: str | None = None
    last_error: str | None = None
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    index: AdminIndexStatus | None = None


class AdminPersonalitySynonym(BaseModel):
    term: str
    language_code: str
    weight: float = Field(gt=0, le=5)
    is_active: bool


class AdminPersonalityTrait(BaseModel):
    code: str
    name_zh: str
    vector_index: int = Field(ge=0, le=15)
    is_active: bool
    synonyms: list[AdminPersonalitySynonym]


class AdminPersonalityTraitUpdate(BaseModel):
    name_zh: str = Field(min_length=1, max_length=40)

    @field_validator("name_zh")
    @classmethod
    def strip_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("人格特質名稱不可為空白。")
        return value.strip()


class AdminPersonalitySynonymCreate(BaseModel):
    term: str = Field(min_length=1, max_length=80)
    language_code: str = Field(default="zh-Hant", min_length=1, max_length=10)
    weight: float = Field(default=2.0, gt=0, le=5)
    is_active: bool = True

    @field_validator("term", "language_code")
    @classmethod
    def strip_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("同義詞與語言代碼不可為空白。")
        return value.strip()


class AdminPersonalitySynonymUpdate(BaseModel):
    original_term: str = Field(min_length=1, max_length=80)
    term: str | None = Field(default=None, min_length=1, max_length=80)
    language_code: str | None = Field(default=None, min_length=1, max_length=10)
    weight: float | None = Field(default=None, gt=0, le=5)
    is_active: bool | None = None

    @field_validator("original_term", "term", "language_code")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("同義詞與語言代碼不可為空白。")
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        changes = self.model_fields_set - {"original_term"}
        if not changes:
            raise ValueError("至少提供一個要修改的欄位。")
        if any(getattr(self, field) is None for field in changes):
            raise ValueError("修改欄位不可為 null。")
        return self
