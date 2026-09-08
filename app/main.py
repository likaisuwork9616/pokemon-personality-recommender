from contextlib import asynccontextmanager
import json
import logging
import os
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.api.admin import router as admin_router
from app.api.catalog import router as catalog_router
from app.api.personality import router as personality_router
from app.api.v1 import router as v1_router
from app.services.admin_auth import AdminAuth, AdminAuthConfig
from app.services.embedding import DEFAULT_MODEL_NAME
from app.services.rag import GroundedExplanationService
from app.services.recommendation import HybridRecommendationEngine
from app.services.observability import RequestMetrics
from app.services.reranking import CrossEncoderConfig, CrossEncoderReranker
from app.web.routes import router as web_router

EngineFactory = Callable[[], Any]


def _personality_refresh_healthy(engine: Any) -> bool:
    if engine is None:
        return False
    try:
        return bool(getattr(engine, "personality_refresh_healthy", True))
    except Exception:
        return False


def _default_engine_factory() -> Any:
    import pandas as pd

    from app.db.session import get_session_factory
    from app.repositories import (
        PersonalityRepository,
        PokemonRepository,
        VectorRepository,
    )
    from app.services.personality_profile import PokemonPersonalityProfile

    session_factory = get_session_factory()

    def load_profile_records() -> list[dict[str, object]]:
        with session_factory() as session:
            return PokemonRepository(session).recommender_records()

    records = load_profile_records()
    with session_factory() as session:
        personality_catalog = PersonalityRepository(session).catalog()
        personality_revision = PersonalityRepository(session).revision()
        vector_repository = VectorRepository(session)
        active_model = vector_repository.active_model()
        ready_pokemon = vector_repository.ready_pokemon_count(active_model.id)
    if not records:
        raise RuntimeError("PostgreSQL 尚無寶可夢資料，請先執行 scripts/import_pokemon.py")
    if ready_pokemon < 3:
        raise RuntimeError("pgvector 索引少於 3 隻可推薦的寶可夢")

    expected_model_name = os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL_NAME)
    expected_model_version = os.getenv("EMBEDDING_MODEL_VERSION", "default")
    if (
        active_model.model_name != expected_model_name
        or active_model.model_version != expected_model_version
        or not active_model.normalize_embeddings
    ):
        raise RuntimeError("目前 active embedding model 與 API query encoder 設定不一致")

    profile_engine = PokemonPersonalityProfile(
        dataframe=pd.DataFrame.from_records(records),
        personality_traits=personality_catalog.trait_names,
        persona_keywords=personality_catalog.synonyms_by_trait,
    )
    reranker_config = CrossEncoderConfig.from_env()
    return HybridRecommendationEngine(
        profile_engine=profile_engine,
        session_factory=session_factory,
        embedding_model_id=active_model.id,
        explanation_service=GroundedExplanationService.from_env(),
        profile_records_loader=load_profile_records,
        personality_revision=personality_revision,
        reranker=(
            CrossEncoderReranker(reranker_config)
            if reranker_config.enabled
            else None
        ),
    )

def create_app(
    engine_factory: EngineFactory | None = None,
    *,
    admin_auth: AdminAuth | None = None,
) -> FastAPI:
    factory = engine_factory or _default_engine_factory
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            application.state.recommendation_engine = factory()
            application.state.readiness_error = None
        except Exception as exc:
            application.state.recommendation_engine = None
            application.state.readiness_error = f"{type(exc).__name__}: {exc}"[:500]
        yield
        application.state.recommendation_engine = None
    application = FastAPI(title="Pokemon Personality Recommender API", description="以人格、屬性權重與語意證據推薦寶可夢，並為 Top 1 產生契合分析。", version="2.1.0", lifespan=lifespan)
    application.state.admin_auth = admin_auth or AdminAuth(AdminAuthConfig.from_env())
    application.state.request_metrics = RequestMetrics()

    @application.middleware("http")
    async def observe_requests(request: Request, call_next):
        request_id = uuid4().hex
        request.state.request_id = request_id
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration = perf_counter() - started
            route = getattr(request.scope.get("route"), "path", "__unmatched__")
            application.state.request_metrics.observe(request.method, route, status_code, duration)
            logging.getLogger("pokemon.http").info(json.dumps({
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "route": route,
                "status": status_code,
                "duration_ms": round(duration * 1000, 3),
            }, separators=(",", ":")))
    application.include_router(v1_router)
    application.include_router(admin_router)
    application.include_router(catalog_router)
    application.include_router(personality_router)
    application.include_router(web_router)
    application.mount("/static", StaticFiles(directory="app/static"), name="static")

    @application.exception_handler(RequestValidationError)
    async def sanitized_validation_error(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """Return useful validation metadata without echoing private input."""

        errors = [
            {
                "location": list(error.get("loc", ())),
                "message": error.get("msg", "Invalid request"),
                "type": error.get("type", "value_error"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "request_validation_error",
                    "message": "Request validation failed",
                    "errors": errors,
                }
            },
        )

    @application.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]: return {"status": "ok"}
    @application.get("/health/ready", tags=["health"])
    async def ready() -> JSONResponse:
        engine = getattr(application.state, "recommendation_engine", None)
        engine_available = engine is not None
        personality_healthy = _personality_refresh_healthy(engine)
        is_ready = engine_available and personality_healthy
        content = {"status": "ready" if is_ready else "not_ready"}
        if not is_ready:
            content["reason"] = (
                "personality_refresh_pending"
                if engine_available and not personality_healthy
                else "engine_unavailable"
            )
        return JSONResponse(status_code=200 if is_ready else 503, content=content)
    @application.get("/metrics", tags=["observability"], include_in_schema=False)
    async def metrics() -> PlainTextResponse:
        engine = getattr(application.state, "recommendation_engine", None)
        return PlainTextResponse(
            application.state.request_metrics.render_prometheus(
                personality_refresh_healthy=_personality_refresh_healthy(engine),
            ),
            media_type="text/plain; version=0.0.4",
        )
    return application

app = create_app()
