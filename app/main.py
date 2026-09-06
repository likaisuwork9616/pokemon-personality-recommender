from contextlib import asynccontextmanager
import os
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.catalog import router as catalog_router
from app.api.v1 import create_recommendation, router as v1_router
from app.schemas import RecommendationResponse
from app.services.embedding import DEFAULT_MODEL_NAME
from app.services.recommendation import HybridRecommendationEngine
from app.web.routes import router as web_router

EngineFactory = Callable[[], Any]

def _default_engine_factory() -> Any:
    import numpy as np
    import pandas as pd

    from app.db.session import get_session_factory
    from app.repositories import PokemonRepository, VectorRepository
    from pokedex_online import PokemonRecommender

    session_factory = get_session_factory()
    with session_factory() as session:
        records = PokemonRepository(session).recommender_records()
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

    # The legacy class remains the deterministic personality-profile component.
    # Its corpus matrix is deliberately unused: semantic retrieval now stays in
    # PostgreSQL and returns traceable chunk evidence for every request.
    profile_engine = PokemonRecommender(
        dataframe=pd.DataFrame.from_records(records),
        pokemon_embeddings=np.zeros((len(records), 384), dtype=float),
    )
    return HybridRecommendationEngine(
        profile_engine=profile_engine,
        session_factory=session_factory,
        embedding_model_id=active_model.id,
    )

def create_app(engine_factory: EngineFactory | None = None) -> FastAPI:
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
    application = FastAPI(title="Pokemon Personality Recommender API", description="以人格與語意證據推薦 Top 3 寶可夢。", version="2.1.0", lifespan=lifespan)
    application.include_router(v1_router)
    application.include_router(catalog_router)
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
        is_ready = getattr(application.state, "recommendation_engine", None) is not None
        return JSONResponse(status_code=200 if is_ready else 503, content={"status": "ready" if is_ready else "not_ready"})
    application.add_api_route("/recommend", create_recommendation, methods=["POST"], response_model=RecommendationResponse, deprecated=True)
    return application

app = create_app()
