from contextlib import asynccontextmanager
from typing import Any, Callable
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from app.api.v1 import create_recommendation, router as v1_router
from app.schemas import RecommendationResponse

EngineFactory = Callable[[], Any]

def _default_engine_factory() -> Any:
    from pokedex_online import FILE_PATH, PokemonRecommender
    return PokemonRecommender(FILE_PATH)

def create_app(engine_factory: EngineFactory | None = None) -> FastAPI:
    factory = engine_factory or _default_engine_factory
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.recommendation_engine = factory()
        yield
        application.state.recommendation_engine = None
    application = FastAPI(title="Pokemon Personality Recommender API", description="以人格與語意證據推薦 Top 3 寶可夢。", version="2.1.0", lifespan=lifespan)
    application.include_router(v1_router)
    @application.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]: return {"status": "ok"}
    @application.get("/health/ready", tags=["health"])
    async def ready() -> JSONResponse:
        is_ready = getattr(application.state, "recommendation_engine", None) is not None
        return JSONResponse(status_code=200 if is_ready else 503, content={"status": "ready" if is_ready else "not_ready"})
    application.add_api_route("/recommend", create_recommendation, methods=["POST"], response_model=RecommendationResponse, deprecated=True)
    return application

app = create_app()
