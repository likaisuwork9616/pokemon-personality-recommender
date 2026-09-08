from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from app.schemas import PokemonSummary, RecommendationRequest, RecommendationResponse, RecommendationResult
from app.services.recommendation import RetrievalUnavailableError

router = APIRouter(prefix="/api/v1")

def _engine(request: Request) -> Any:
    engine = getattr(request.app.state, "recommendation_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail={"code": "service_not_ready", "message": "推薦模型尚未完成載入"})
    return engine

def _to_result(raw: dict[str, Any], explanation: dict[str, Any] | None) -> RecommendationResult:
    return RecommendationResult(
        rank=raw["rank"],
        pokemon=PokemonSummary(
            id=raw["database_id"],
            pokedex_number=raw["pokedex_number"],
            name_zh=raw.get("name", ""),
            name_en=raw.get("name_en", ""),
            types=raw.get("type", ""),
            image_url=raw.get("img") or None,
        ),
        scores=raw["scores"],
        evidence=raw.get("matching_evidence", []),
        explanation=explanation,
    )

async def create_recommendation(payload: RecommendationRequest, request: Request) -> RecommendationResponse:
    engine = _engine(request)
    try:
        def run_recommendation() -> RecommendationResponse:
            raw_results = engine.recommend(payload.text.strip(), top_k=3)
            explanations: dict[int, dict[str, Any]] = {}
            if payload.generate_explanation:
                top_result = raw_results[0]
                explain_results = getattr(engine, "explain_results", None)
                if callable(explain_results):
                    explanations = explain_results(payload.text, [top_result])
                else:
                    explanations = {
                        int(top_result["database_id"]): engine.explain(
                            payload.text,
                            top_result,
                        )
                    }
            return RecommendationResponse(
                algorithm_version=(
                    "pgvector-fts-rrf-cross-encoder-v1"
                    if getattr(engine, "reranker", None) is not None
                    else "pgvector-fts-rrf-v1"
                ),
                results=[
                    _to_result(
                        raw,
                        explanations.get(int(raw["database_id"])),
                    )
                    for raw in raw_results
                ]
            )

        return await run_in_threadpool(run_recommendation)
    except RetrievalUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "retrieval_unavailable",
                "message": str(exc),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "invalid_recommendation_input", "message": str(exc)}) from exc

router.add_api_route(
    "/recommendations",
    create_recommendation,
    methods=["POST"],
    response_model=RecommendationResponse,
    summary="取得 Top 3 排名與 Top 1 契合分析",
)
