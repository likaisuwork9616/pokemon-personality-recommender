"""Public read-only personality vocabulary routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_personality_repository
from app.repositories import PersonalityRepository
from app.schemas import (
    PublicPersonalityCatalog,
    PublicPersonalityTrait,
    PublicPersonalityWeightedTerm,
)
from app.services.personality_profile import (
    TYPE_PERSONALITY_WEIGHTS,
    TYPE_PERSONALITY_WEIGHTS_VERSION,
)


router = APIRouter(prefix="/api/v1/personality", tags=["personality vocabulary"])


def _type_profile_count(*, trait_count: int) -> int:
    if trait_count != 16:
        raise RuntimeError("type weights require exactly 16 personality traits")
    if len(TYPE_PERSONALITY_WEIGHTS) != 18 or any(
        len(weights) != trait_count
        for weights in TYPE_PERSONALITY_WEIGHTS.values()
    ):
        raise RuntimeError("type personality weight dimensions are inconsistent")
    return len(TYPE_PERSONALITY_WEIGHTS)


@router.get(
    "/traits",
    response_model=PublicPersonalityCatalog,
    summary="列出啟用中的加權人格特質",
)
def list_personality_traits(
    response: Response,
    repository: Annotated[PersonalityRepository, Depends(get_personality_repository)],
) -> PublicPersonalityCatalog:
    try:
        catalog = repository.public_catalog()
        type_profile_count = _type_profile_count(trait_count=len(catalog.traits))
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "personality_catalog_unavailable",
                "message": "人格特質資料暫時無法使用。",
            },
        ) from None

    response.headers["Cache-Control"] = "public, max-age=60"
    response.headers["ETag"] = (
        f'"personality-v{catalog.revision}-{TYPE_PERSONALITY_WEIGHTS_VERSION}"'
    )
    return PublicPersonalityCatalog(
        revision=catalog.revision,
        traits=[
            PublicPersonalityTrait(
                code=trait.code,
                name_zh=trait.name_zh,
                weighted_terms=[
                    PublicPersonalityWeightedTerm(term=term.term, weight=term.weight)
                    for term in trait.weighted_terms
                ],
            )
            for trait in catalog.traits
        ],
        type_weight_version=TYPE_PERSONALITY_WEIGHTS_VERSION,
        type_profile_count=type_profile_count,
    )
