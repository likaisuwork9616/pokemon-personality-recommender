"""Public MBTI reference content from the immutable bundled catalog."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.schemas import PublicPersonalityCatalog, PublicPersonalityTrait
from app.services.mbti_catalog import MbtiCatalog, get_mbti_catalog


router = APIRouter(prefix="/api/v1/personality", tags=["MBTI reference"])


def public_mbti_catalog(catalog: MbtiCatalog) -> PublicPersonalityCatalog:
    return PublicPersonalityCatalog(
        revision=catalog.revision,
        catalog_version=catalog.version,
        reviewed_at=catalog.reviewed_at,
        traits=[PublicPersonalityTrait(**asdict(profile)) for profile in catalog.profiles],
    )


def get_public_mbti_catalog() -> MbtiCatalog:
    try:
        return get_mbti_catalog()
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail={"code": "personality_catalog_unavailable", "message": "MBTI 介紹暫時無法使用。"},
        ) from None


@router.get("/traits", response_model=PublicPersonalityCatalog, summary="列出十六型 MBTI 詳細介紹")
def list_personality_traits(
    response: Response,
    catalog: Annotated[MbtiCatalog, Depends(get_public_mbti_catalog)],
) -> PublicPersonalityCatalog:
    response.headers["Cache-Control"] = "public, max-age=60"
    response.headers["ETag"] = f'"{catalog.version}-r{catalog.revision}-{catalog.content_hash[:16]}"'
    return public_mbti_catalog(catalog)
