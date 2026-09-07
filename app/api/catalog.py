"""Public searchable and paginated Pokemon catalog routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.api.deps import get_pokemon_repository
from app.repositories import PokemonRepository
from app.schemas.catalog import (
    CatalogAbilityTerm,
    CatalogDescription,
    CatalogImage,
    CatalogLocalizedTerm,
    CatalogPage,
    CatalogPokemon,
    CatalogStats,
    CatalogType,
    PokemonDetail,
)
from app.services.catalog_localization import (
    LocalizedTerm,
    localize_ability_terms,
    localize_catalog_term,
    localize_catalog_terms,
)

router = APIRouter(prefix="/api/v1/pokemon", tags=["pokemon catalog"])


def _types(pokemon: Any) -> list[CatalogType]:
    return [
        CatalogType(
            slot=link.slot,
            code=link.type_record.code,
            name_en=link.type_record.name_en,
            name_zh=link.type_record.name_zh,
        )
        for link in sorted(pokemon.type_links, key=lambda item: item.slot)
    ]


def _images(pokemon: Any) -> list[Any]:
    return sorted(
        pokemon.images,
        key=lambda image: (not image.is_primary, image.image_kind, image.id),
    )


def _primary_image(pokemon: Any) -> str | None:
    images = _images(pokemon)
    return images[0].image_url if images else None


def _is_public_description(item: Any) -> bool:
    return (
        str(item.language_code).strip().casefold() == "zh-hant"
        and str(item.description_kind).strip().casefold() == "description"
    )


def _localized_term(term: LocalizedTerm | None) -> CatalogLocalizedTerm | None:
    if term is None:
        return None
    return CatalogLocalizedTerm(code=term.code, name_zh=term.name_zh)


def _localized_profile(pokemon: Any) -> dict[str, Any]:
    ability_details = localize_ability_terms(
        pokemon.abilities,
        pokemon.hidden_ability,
    )
    return {
        "ability_details": [
            CatalogAbilityTerm(
                code=term.code,
                name_zh=term.name_zh,
                is_hidden=term.is_hidden,
            )
            for term in ability_details
        ],
        "egg_group_details": [
            CatalogLocalizedTerm(code=term.code, name_zh=term.name_zh)
            for term in localize_catalog_terms(pokemon.egg_groups, "egg_group")
        ],
        "habitat_detail": _localized_term(
            localize_catalog_term(pokemon.habitat, "habitat")
        ),
        "growth_rate_detail": _localized_term(
            localize_catalog_term(pokemon.growth_rate, "growth_rate")
        ),
    }


def _catalog_item(pokemon: Any) -> CatalogPokemon:
    return CatalogPokemon(
        id=pokemon.id,
        pokedex_number=pokemon.pokedex_number,
        form_key=pokemon.form_key,
        name_zh=pokemon.name_zh,
        name_en=pokemon.name_en,
        types=_types(pokemon),
        generation=pokemon.generation,
        is_legendary=pokemon.is_legendary,
        is_mythical=pokemon.is_mythical,
        image_url=_primary_image(pokemon),
    )


@router.get("", response_model=CatalogPage, summary="搜尋與瀏覽寶可夢圖鑑")
def list_pokemon(
    repository: Annotated[PokemonRepository, Depends(get_pokemon_repository)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    type_filter: Annotated[
        str | None,
        Query(alias="type", min_length=1, max_length=40),
    ] = None,
    generation: Annotated[int | None, Query(ge=1, le=9)] = None,
    is_legendary: bool | None = None,
    is_mythical: bool | None = None,
) -> CatalogPage:
    items, total = repository.search_catalog(
        q=q,
        page=page,
        page_size=page_size,
        type_code=type_filter,
        generation=generation,
        is_legendary=is_legendary,
        is_mythical=is_mythical,
    )
    return CatalogPage(
        items=[_catalog_item(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/{pokemon_id}", response_model=PokemonDetail, summary="取得寶可夢詳細資料")
def pokemon_detail(
    pokemon_id: Annotated[int, Path(ge=1)],
    repository: Annotated[PokemonRepository, Depends(get_pokemon_repository)],
) -> PokemonDetail:
    pokemon = repository.get_catalog_detail(pokemon_id)
    if pokemon is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "pokemon_not_found",
                "message": "找不到指定的寶可夢。",
            },
        )

    stats = pokemon.stats
    return PokemonDetail(
        **_catalog_item(pokemon).model_dump(),
        category_zh=pokemon.category_zh,
        genus=pokemon.genus,
        descriptions=[
            CatalogDescription(
                id=item.id,
                language_code=item.language_code,
                description_kind=item.description_kind,
                source_key=item.source_key,
                content=item.content,
                content_hash=item.content_hash,
                is_primary=item.is_primary,
            )
            for item in sorted(
                (
                    item
                    for item in pokemon.descriptions
                    if _is_public_description(item)
                ),
                key=lambda item: (
                    item.language_code,
                    item.description_kind,
                    item.source_key,
                    item.id,
                ),
            )
        ],
        stats=(
            CatalogStats(
                hp=stats.hp,
                attack=stats.attack,
                defense=stats.defense,
                sp_attack=stats.sp_attack,
                sp_defense=stats.sp_defense,
                speed=stats.speed,
                base_stat_total=stats.base_stat_total,
            )
            if stats is not None
            else None
        ),
        images=[
            CatalogImage(
                id=item.id,
                image_kind=item.image_kind,
                image_url=item.image_url,
                is_primary=item.is_primary,
            )
            for item in _images(pokemon)
        ],
        height_m=pokemon.height_m,
        weight_kg=pokemon.weight_kg,
        abilities=pokemon.abilities,
        hidden_ability=pokemon.hidden_ability,
        egg_groups=pokemon.egg_groups,
        habitat=pokemon.habitat,
        color=pokemon.color,
        shape=pokemon.shape,
        growth_rate=pokemon.growth_rate,
        **_localized_profile(pokemon),
        capture_rate=pokemon.capture_rate,
        is_baby=pokemon.is_baby,
    )
