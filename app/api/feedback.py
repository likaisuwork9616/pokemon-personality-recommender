"""Public bounded recommendation feedback and aggregate admin reporting."""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from app.api.admin import require_admin
from app.repositories.recommendation_feedback import (
    FeedbackItemMismatch,
    FeedbackReceiptNotFound,
)
from app.schemas.recommendation import (
    RecommendationFeedbackRequest,
    RecommendationFeedbackResponse,
    RecommendationFeedbackSummary,
)
from app.services.admin_auth import AdminSession


router = APIRouter(prefix="/api/v1", tags=["recommendation feedback"])


def _feedback_service(request: Request) -> Any:
    service = getattr(request.app.state, "feedback_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "feedback_unavailable",
                "message": "回饋服務目前無法使用，推薦結果不受影響。",
            },
        )
    return service


@router.post(
    "/recommendation-feedback",
    response_model=RecommendationFeedbackResponse,
    summary="回報當次 Top 3 推薦是否符合",
)
async def submit_recommendation_feedback(
    payload: RecommendationFeedbackRequest,
    request: Request,
) -> RecommendationFeedbackResponse:
    service = _feedback_service(request)
    try:
        created = await run_in_threadpool(
            service.submit_feedback,
            recommendation_id=payload.recommendation_id,
            pokemon_id=payload.pokemon_id,
            rank=payload.rank,
            verdict=payload.verdict,
            reason=payload.reason,
        )
        return RecommendationFeedbackResponse(created=created)
    except FeedbackReceiptNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "feedback_receipt_not_found", "message": str(exc)},
        ) from None
    except FeedbackItemMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "feedback_item_mismatch", "message": str(exc)},
        ) from None
    except Exception as exc:
        logging.getLogger("pokemon.feedback").warning(
            json.dumps(
                {
                    "event": "feedback_submission_failed",
                    "error_type": type(exc).__name__,
                },
                separators=(",", ":"),
            )
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "feedback_unavailable",
                "message": "回饋暫時無法保存，請稍後再試。",
            },
        ) from None


@router.get(
    "/admin/feedback/summary",
    response_model=RecommendationFeedbackSummary,
    summary="查看匿名推薦回饋彙總",
)
async def recommendation_feedback_summary(
    request: Request,
    _admin_session: Annotated[AdminSession, Depends(require_admin)],
) -> RecommendationFeedbackSummary:
    service = _feedback_service(request)
    try:
        summary = await run_in_threadpool(service.summary)
        return RecommendationFeedbackSummary.model_validate(summary)
    except Exception as exc:
        logging.getLogger("pokemon.feedback").warning(
            json.dumps(
                {
                    "event": "feedback_summary_failed",
                    "error_type": type(exc).__name__,
                },
                separators=(",", ":"),
            )
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "feedback_summary_unavailable",
                "message": "回饋彙總目前無法讀取。",
            },
        ) from None
