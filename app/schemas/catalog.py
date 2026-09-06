"""Schemas for the public Pokemon catalog API."""

from pydantic import BaseModel, Field


class CatalogType(BaseModel):
    slot: int = Field(ge=1, le=2)
    code: str
    name_en: str
    name_zh: str


class CatalogPokemon(BaseModel):
    id: int
    pokedex_number: int
    form_key: str
    name_zh: str
    name_en: str
    types: list[CatalogType]
    generation: int = Field(ge=1, le=9)
    is_legendary: bool
    is_mythical: bool
    image_url: str | None = None


class CatalogPage(BaseModel):
    items: list[CatalogPokemon]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class CatalogDescription(BaseModel):
    id: int
    language_code: str
    description_kind: str
    source_key: str
    content: str
    content_hash: str


class CatalogImage(BaseModel):
    id: int
    image_kind: str
    image_url: str
    is_primary: bool


class CatalogStats(BaseModel):
    hp: int | None = None
    attack: int | None = None
    defense: int | None = None
    sp_attack: int | None = None
    sp_defense: int | None = None
    speed: int | None = None
    base_stat_total: int | None = None


class PokemonDetail(CatalogPokemon):
    category_zh: str | None = None
    genus: str | None = None
    descriptions: list[CatalogDescription]
    stats: CatalogStats | None = None
    images: list[CatalogImage]
    height_m: float | None = None
    weight_kg: float | None = None
    abilities: str
    hidden_ability: str | None = None
    egg_groups: str
    habitat: str | None = None
    color: str | None = None
    shape: str | None = None
    growth_rate: str | None = None
    capture_rate: int | None = None
    is_baby: bool
