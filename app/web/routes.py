"""Lightweight Jinja page shells backed by the public JSON API."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


APP_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

router = APIRouter(include_in_schema=False)


@router.get("/admin", response_class=HTMLResponse, name="pokemon_admin")
async def admin_page(request: Request) -> HTMLResponse:
    """Render the same-origin administrator shell without exposing secrets."""

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={"page_title": "寶可夢資料管理"},
    )


@router.get("/pokemon", response_class=HTMLResponse, name="pokemon_catalog")
async def catalog_page(request: Request) -> HTMLResponse:
    """Render the searchable catalog shell; data is loaded from the v1 API."""

    return templates.TemplateResponse(
        request=request,
        name="catalog.html",
        context={"page_title": "寶可夢圖鑑"},
    )


@router.get(
    "/pokemon/{pokemon_id}",
    response_class=HTMLResponse,
    name="pokemon_detail",
)
async def pokemon_detail_page(request: Request, pokemon_id: int) -> HTMLResponse:
    """Render a detail shell that resolves one active Pokémon through the API."""

    return templates.TemplateResponse(
        request=request,
        name="pokemon_detail.html",
        context={
            "page_title": "寶可夢資料",
            "pokemon_id": pokemon_id,
        },
    )
