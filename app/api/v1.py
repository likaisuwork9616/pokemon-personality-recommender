import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from starlette.concurrency import run_in_threadpool

from app.schemas import (
    PokemonSummary,
    RecommendationRequest,
    RecommendationResponse,
    RecommendationResult,
    TodayCalendarResponse,
    TodayFortuneResponse,
    TodayPokemonResponse,
    TodayPokemonSelectionResponse,
    TodayZodiacResponse,
)
from app.services.recommendation import RetrievalUnavailableError
from app.today_pokemon_rules import ZodiacSign

router = APIRouter(prefix="/api/v1")

def _engine(request: Request) -> Any:
    engine = getattr(request.app.state, "recommendation_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail={"code": "service_not_ready", "message": "推薦模型尚未完成載入"})
    return engine


def _today_service(request: Request) -> Any:
    service = getattr(request.app.state, "today_pokemon_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "service_not_ready", "message": "今日寶可夢服務尚未完成載入"},
        )
    return service

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


def _enforce_recommendation_rate_limit(
    request: Request,
    response: Response,
    *,
    explanation_requested: bool,
) -> None:
    guard = getattr(request.app.state, "recommendation_abuse_guard", None)
    if guard is None:
        return
    client_identity = request.client.host if request.client is not None else "unknown"
    decision = guard.check(
        client_identity,
        explanation_requested=explanation_requested,
    )
    response.headers["X-RateLimit-Limit"] = str(decision.limit)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
    if decision.allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "recommendation_rate_limited",
            "message": "請稍候再試，公開推薦服務目前請求過多。",
        },
        headers={
            "Retry-After": str(decision.retry_after_seconds),
            "X-RateLimit-Limit": str(decision.limit),
            "X-RateLimit-Remaining": "0",
        },
    )


async def create_recommendation(
    payload: RecommendationRequest,
    request: Request,
    response: Response,
) -> RecommendationResponse:
    _enforce_recommendation_rate_limit(
        request,
        response,
        explanation_requested=payload.generate_explanation,
    )
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
            algorithm_version = (
                    "pgvector-fts-rrf-cross-encoder-v1"
                    if getattr(engine, "reranker", None) is not None
                    else "pgvector-fts-rrf-v1"
                )
            response = RecommendationResponse(
                algorithm_version=algorithm_version,
                results=[
                    _to_result(
                        raw,
                        explanations.get(int(raw["database_id"])),
                    )
                    for raw in raw_results
                ]
            )
            feedback_service = getattr(request.app.state, "feedback_service", None)
            if feedback_service is not None:
                try:
                    recommendation_id = feedback_service.record_impression(
                        algorithm_version=algorithm_version,
                        ranked_pokemon=[
                            (int(raw["rank"]), int(raw["database_id"]))
                            for raw in raw_results
                        ],
                    )
                    response = response.model_copy(
                        update={"recommendation_id": recommendation_id}
                    )
                except Exception as exc:
                    logging.getLogger("pokemon.feedback").warning(
                        json.dumps(
                            {
                                "event": "feedback_impression_failed",
                                "error_type": type(exc).__name__,
                            },
                            separators=(",", ":"),
                        )
                    )
            return response

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


@router.get(
    "/today-pokemon",
    response_model=TodayPokemonResponse,
    summary="取得目前台北日期與時辰的代表寶可夢",
)
async def get_today_pokemon(
    zodiac: ZodiacSign,
    request: Request,
    response: Response,
) -> TodayPokemonResponse:
    _enforce_recommendation_rate_limit(
        request,
        response,
        explanation_requested=True,
    )
    service = _today_service(request)
    try:
        def run_selection() -> TodayPokemonResponse:
            outcome = service.select(zodiac)
            explanation = service.explain(outcome)
            raw = outcome.pokemon
            return TodayPokemonResponse(
                algorithm_version=outcome.algorithm_version,
                generated_at=outcome.calendar.generated_at,
                valid_until=outcome.calendar.valid_until,
                zodiac=TodayZodiacResponse(
                    code=outcome.zodiac.code,
                    name_zh=outcome.zodiac.name_zh,
                    symbol=outcome.zodiac.symbol,
                    date_range=outcome.zodiac.date_range,
                    element=outcome.zodiac.element,
                    modality=outcome.zodiac.modality,
                    traits=list(outcome.signal_trait_labels),
                ),
                calendar=TodayCalendarResponse(
                    solar_date=outcome.calendar.solar_date,
                    weekday_zh=outcome.calendar.weekday_zh,
                    time_hm=outcome.calendar.time_hm,
                    lunar_date_zh=outcome.calendar.lunar_date_zh,
                    lunar_year_ganzhi=outcome.calendar.lunar_year_ganzhi,
                    lunar_month_ganzhi=outcome.calendar.lunar_month_ganzhi,
                    lunar_day_ganzhi=outcome.calendar.lunar_day_ganzhi,
                    time_ganzhi=outcome.calendar.time_ganzhi,
                    time_branch=outcome.calendar.time_branch,
                    solar_term=outcome.calendar.solar_term,
                    season=outcome.calendar.season,
                    lunar_phase=outcome.calendar.lunar_phase,
                ),
                calendar_signals=list(outcome.calendar_signals),
                selection=TodayPokemonSelectionResponse(
                    pokemon=PokemonSummary(
                        id=raw["database_id"],
                        pokedex_number=raw["pokedex_number"],
                        name_zh=raw.get("name", ""),
                        name_en=raw.get("name_en", ""),
                        types=raw.get("type", ""),
                        image_url=raw.get("img") or None,
                    ),
                    source_rank=outcome.source_rank,
                    selection_score=outcome.selection_score,
                    pokemon_traits=list(raw.get("pokemon_traits", [])),
                    type_affinities=list(outcome.type_affinities),
                    evidence=list(raw.get("matching_evidence", [])),
                    explanation=explanation,
                ),
                fortune=TodayFortuneResponse(
                    overall=outcome.fortune.overall,
                    work_study=outcome.fortune.work_study,
                    relationships=outcome.fortune.relationships,
                    vitality=outcome.fortune.vitality,
                    action=outcome.fortune.action,
                    reminder=outcome.fortune.reminder,
                    disclaimer=outcome.fortune.disclaimer,
                ),
            )

        result = await run_in_threadpool(run_selection)
        max_age = max(
            0,
            int((result.valid_until - result.generated_at).total_seconds()) - 30,
        )
        response.headers["Cache-Control"] = f"private, max-age={max_age}"
        return result
    except RetrievalUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "retrieval_unavailable", "message": str(exc)},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logging.getLogger("pokemon.today").warning(
            json.dumps(
                {"event": "today_pokemon_failed", "error_type": type(exc).__name__},
                separators=(",", ":"),
            )
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "today_pokemon_unavailable",
                "message": "今日寶可夢暫時無法產生",
            },
        ) from exc
