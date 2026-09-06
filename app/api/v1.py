from typing import Any
from fastapi import APIRouter, HTTPException, Request, status
from app.schemas import PokemonSummary, RecommendationRequest, RecommendationResponse, RecommendationResult

router = APIRouter(prefix="/api/v1")

def _engine(request: Request) -> Any:
    engine = getattr(request.app.state, "recommendation_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail={"code": "service_not_ready", "message": "推薦模型尚未完成載入"})
    return engine

def _to_result(raw: dict[str, Any], explanation: str | None) -> RecommendationResult:
    return RecommendationResult(rank=raw["rank"], pokemon=PokemonSummary(pokedex_number=raw["pokedex_number"], name_zh=raw.get("name", ""), name_en=raw.get("name_en", ""), types=raw.get("type", ""), image_url=raw.get("img") or None), scores=raw["scores"], evidence=raw.get("matching_evidence", []), explanation=explanation)

async def create_recommendation(payload: RecommendationRequest, request: Request) -> RecommendationResponse:
    engine = _engine(request)
    try:
        raw_results = engine.recommend(payload.text.strip(), top_k=3)
        return RecommendationResponse(results=[_to_result(raw, engine.explain(payload.text, raw) if payload.generate_explanation else None) for raw in raw_results])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "invalid_recommendation_input", "message": str(exc)}) from exc

router.add_api_route("/recommendations", create_recommendation, methods=["POST"], response_model=RecommendationResponse, summary="取得 Top 3 寶可夢人格推薦")
