"""Authenticated administrator API for Pokémon lifecycle management."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.catalog import _catalog_item, _images
from app.api.deps import get_session
from app.repositories.admin import AdminPokemonRepository
from app.repositories.personality_admin import AdminPersonalityRepository
from app.repositories.reindex import PokemonIndexState, PokemonReindexRepository
from app.repositories.reindex_jobs import PokemonReindexJobRepository
from app.repositories.vector import VectorRepository
from app.schemas.admin import (
    AdminIndexSourceStatus,
    AdminIndexStatus,
    AdminLoginRequest,
    AdminPersonalitySynonym,
    AdminPersonalitySynonymCreate,
    AdminPersonalitySynonymUpdate,
    AdminPersonalityTrait,
    AdminPersonalityTraitUpdate,
    AdminPokemonCreate,
    AdminPokemonDetail,
    AdminPokemonPage,
    AdminPokemonSummary,
    AdminPokemonUpdate,
    AdminReindexJobResponse,
    AdminSessionResponse,
)
from app.schemas.catalog import CatalogDescription, CatalogImage, CatalogStats
from app.services.admin_auth import (
    AdminAuth,
    AdminDisabledError,
    AdminSession,
    InvalidAdminCredentials,
    InvalidAdminSession,
    InvalidCsrfToken,
)
from app.services.reindex import (
    PokemonNotFoundError,
    PokemonReindexService,
)


router = APIRouter(prefix="/api/v1/admin", tags=["pokemon administration"])


def get_admin_repository(
    session: Annotated[Session, Depends(get_session)],
) -> AdminPokemonRepository:
    return AdminPokemonRepository(session)


def get_admin_personality_repository(
    session: Annotated[Session, Depends(get_session)],
) -> AdminPersonalityRepository:
    return AdminPersonalityRepository(session)


def get_admin_auth(request: Request) -> AdminAuth:
    return request.app.state.admin_auth


def get_reindex_service(
    session: Annotated[Session, Depends(get_session)],
) -> PokemonReindexService:
    return PokemonReindexService(
        PokemonReindexRepository(session),
        VectorRepository(session),
    )


def get_reindex_job_repository(
    session: Annotated[Session, Depends(get_session)],
) -> PokemonReindexJobRepository:
    return PokemonReindexJobRepository(session)


def require_admin(
    request: Request,
    auth: Annotated[AdminAuth, Depends(get_admin_auth)],
) -> AdminSession:
    try:
        return auth.verify_session(request.cookies.get(auth.config.cookie_name))
    except AdminDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "admin_disabled", "message": str(exc)},
        ) from None
    except InvalidAdminSession:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "admin_auth_required", "message": "需要管理員驗證。"},
        ) from None


def require_csrf(
    admin_session: Annotated[AdminSession, Depends(require_admin)],
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AdminSession:
    try:
        AdminAuth.verify_csrf(admin_session, csrf_token)
    except InvalidCsrfToken:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "invalid_csrf_token", "message": "CSRF 驗證失敗。"},
        ) from None
    return admin_session


def _session_response(admin_session: AdminSession) -> AdminSessionResponse:
    return AdminSessionResponse(
        csrf_token=admin_session.csrf_token,
        expires_at=admin_session.expires_at,
    )


def _detail(pokemon: Any) -> AdminPokemonDetail:
    stats = pokemon.stats
    return AdminPokemonDetail(
        **_catalog_item(pokemon).model_dump(),
        category_zh=pokemon.category_zh,
        genus=pokemon.genus,
        descriptions=[
            CatalogDescription(
                id=item.id,
                language_code=item.language_code,
                description_kind=item.description_kind,
                source_key=item.source_key,
                content=item.content,
                content_hash=item.content_hash,
                is_primary=item.is_primary,
            )
            for item in sorted(
                pokemon.descriptions,
                key=lambda item: (
                    item.language_code,
                    item.description_kind,
                    item.source_key,
                    item.id,
                ),
            )
        ],
        stats=(
            CatalogStats(
                hp=stats.hp,
                attack=stats.attack,
                defense=stats.defense,
                sp_attack=stats.sp_attack,
                sp_defense=stats.sp_defense,
                speed=stats.speed,
                base_stat_total=stats.base_stat_total,
            )
            if stats is not None
            else None
        ),
        images=[
            CatalogImage(
                id=item.id,
                image_kind=item.image_kind,
                image_url=item.image_url,
                is_primary=item.is_primary,
            )
            for item in _images(pokemon)
        ],
        height_m=pokemon.height_m,
        weight_kg=pokemon.weight_kg,
        abilities=pokemon.abilities,
        hidden_ability=pokemon.hidden_ability,
        egg_groups=pokemon.egg_groups,
        habitat=pokemon.habitat,
        color=pokemon.color,
        shape=pokemon.shape,
        growth_rate=pokemon.growth_rate,
        capture_rate=pokemon.capture_rate,
        is_baby=pokemon.is_baby,
        is_active=pokemon.is_active,
    )


def _index_status(state: PokemonIndexState) -> AdminIndexStatus:
    return AdminIndexStatus(
        pokemon_id=state.pokemon_id,
        status=state.status,
        sources=[AdminIndexSourceStatus(**vars(item)) for item in state.sources],
    )


def _job_response(job: Any, index: AdminIndexStatus | None = None) -> AdminReindexJobResponse:
    return AdminReindexJobResponse(
        id=job.id,
        pokemon_id=job.pokemon_id,
        status=job.status,
        progress_current=job.progress_current,
        progress_total=job.progress_total,
        embedded=job.embedded,
        failed=job.failed,
        message=job.message,
        last_error=job.last_error,
        queued_at=job.queued_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        index=index,
    )


def _personality_synonym(item: Any) -> AdminPersonalitySynonym:
    return AdminPersonalitySynonym(
        term=item.term,
        language_code=item.language_code,
        weight=item.weight,
        is_active=item.is_active,
    )


def _personality_trait(item: Any) -> AdminPersonalityTrait:
    return AdminPersonalityTrait(
        code=item.code,
        name_zh=item.name_zh,
        vector_index=item.vector_index,
        is_active=item.is_active,
        synonyms=[
            _personality_synonym(synonym)
            for synonym in sorted(item.synonyms, key=lambda value: (not value.is_active, value.term))
        ],
    )


def _get_or_404(repository: AdminPokemonRepository, pokemon_id: int):
    pokemon = repository.get(pokemon_id)
    if pokemon is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "pokemon_not_found", "message": "找不到指定的寶可夢。"},
        )
    return pokemon


def _commit(repository: AdminPokemonRepository) -> None:
    try:
        repository.session.commit()
    except IntegrityError:
        repository.session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "pokemon_conflict",
                "message": "圖鑑編號、型態或子資料與現有資料衝突。",
            },
        ) from None


def _rollback_conflict(repository: AdminPokemonRepository) -> None:
    repository.session.rollback()
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "pokemon_conflict",
            "message": "圖鑑編號、型態或子資料與現有資料衝突。",
        },
    ) from None


def _refresh_runtime_profiles(request: Request) -> None:
    """Refresh committed catalog changes without making admin writes fail."""

    engine = getattr(request.app.state, "recommendation_engine", None)
    refresh = getattr(engine, "refresh_profiles", None)
    if not callable(refresh):
        return
    try:
        refresh()
        request.app.state.profile_refresh_error = None
    except Exception:
        # The recommendation engine also self-refreshes when it encounters a
        # newly indexed ID. Never roll back an already committed admin edit.
        request.app.state.profile_refresh_error = "profile refresh failed"


def _refresh_runtime_personality(request: Request, repository: AdminPersonalityRepository) -> None:
    engine = getattr(request.app.state, "recommendation_engine", None)
    refresh = getattr(engine, "refresh_personality_catalog", None)
    if not callable(refresh):
        return
    try:
        refresh(repository.catalog(), revision=repository.revision())
        request.app.state.personality_refresh_error = None
    except Exception:
        request.app.state.personality_refresh_error = "personality refresh failed"


def _commit_personality(repository: AdminPersonalityRepository, request: Request) -> None:
    try:
        repository.bump_revision()
        repository.session.commit()
    except IntegrityError:
        repository.session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "personality_conflict", "message": "人格特質名稱或同義詞已存在。"},
        ) from None
    _refresh_runtime_personality(request, repository)


@router.post("/session", response_model=AdminSessionResponse, summary="管理員登入")
def login(payload: AdminLoginRequest, request: Request) -> JSONResponse:
    auth: AdminAuth = request.app.state.admin_auth
    try:
        token, admin_session = auth.login(payload.password)
    except AdminDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "admin_disabled", "message": str(exc)},
        ) from None
    except InvalidAdminCredentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_admin_credentials", "message": "登入失敗。"},
        ) from None
    response = JSONResponse(_session_response(admin_session).model_dump())
    response.set_cookie(
        key=auth.config.cookie_name,
        value=token,
        max_age=auth.config.session_ttl_seconds,
        httponly=True,
        secure=auth.config.cookie_secure,
        samesite="strict",
        path="/",
    )
    return response


@router.get("/session", response_model=AdminSessionResponse, summary="取得管理工作階段")
def session_status(
    admin_session: Annotated[AdminSession, Depends(require_admin)],
) -> AdminSessionResponse:
    return _session_response(admin_session)


@router.delete("/session", status_code=204, summary="管理員登出")
def logout(
    request: Request,
    _admin_session: Annotated[AdminSession, Depends(require_csrf)],
) -> Response:
    auth: AdminAuth = request.app.state.admin_auth
    response = Response(status_code=204)
    response.delete_cookie(
        auth.config.cookie_name,
        path="/",
        secure=auth.config.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return response


@router.get(
    "/personality/traits",
    response_model=list[AdminPersonalityTrait],
    summary="列出人格特質與同義詞",
)
def list_personality_traits(
    _admin_session: Annotated[AdminSession, Depends(require_admin)],
    repository: Annotated[AdminPersonalityRepository, Depends(get_admin_personality_repository)],
) -> list[AdminPersonalityTrait]:
    return [_personality_trait(item) for item in repository.list_traits()]


@router.patch(
    "/personality/traits/{trait_code}",
    response_model=AdminPersonalityTrait,
    summary="修改人格特質名稱",
)
def update_personality_trait(
    payload: AdminPersonalityTraitUpdate,
    request: Request,
    trait_code: str,
    _admin_session: Annotated[AdminSession, Depends(require_csrf)],
    repository: Annotated[AdminPersonalityRepository, Depends(get_admin_personality_repository)],
) -> AdminPersonalityTrait:
    trait = repository.get_trait(trait_code)
    if trait is None:
        raise HTTPException(status_code=404, detail={"code": "trait_not_found", "message": "找不到指定的人格特質。"})
    repository.rename_trait(trait, payload.name_zh)
    _commit_personality(repository, request)
    return _personality_trait(trait)


@router.post(
    "/personality/traits/{trait_code}/synonyms",
    response_model=AdminPersonalitySynonym,
    status_code=status.HTTP_201_CREATED,
    summary="新增人格同義詞",
)
def create_personality_synonym(
    payload: AdminPersonalitySynonymCreate,
    request: Request,
    trait_code: str,
    _admin_session: Annotated[AdminSession, Depends(require_csrf)],
    repository: Annotated[AdminPersonalityRepository, Depends(get_admin_personality_repository)],
) -> AdminPersonalitySynonym:
    trait = repository.get_trait(trait_code)
    if trait is None:
        raise HTTPException(status_code=404, detail={"code": "trait_not_found", "message": "找不到指定的人格特質。"})
    item = repository.add_synonym(trait, **payload.model_dump())
    _commit_personality(repository, request)
    return _personality_synonym(item)


@router.patch(
    "/personality/traits/{trait_code}/synonyms",
    response_model=AdminPersonalitySynonym,
    summary="修改或停用人格同義詞",
)
def update_personality_synonym(
    payload: AdminPersonalitySynonymUpdate,
    request: Request,
    trait_code: str,
    _admin_session: Annotated[AdminSession, Depends(require_csrf)],
    repository: Annotated[AdminPersonalityRepository, Depends(get_admin_personality_repository)],
) -> AdminPersonalitySynonym:
    item = repository.get_synonym(trait_code, payload.original_term)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "synonym_not_found", "message": "找不到指定的人格同義詞。"})
    try:
        changes = payload.model_dump(exclude_unset=True)
        changes.pop("original_term", None)
        repository.update_synonym(item, **changes)
    except ValueError as exc:
        repository.session.rollback()
        raise HTTPException(status_code=422, detail={"code": "invalid_personality_vocabulary", "message": str(exc)}) from None
    _commit_personality(repository, request)
    return _personality_synonym(item)


@router.get("/pokemon", response_model=AdminPokemonPage, summary="列出所有寶可夢")
def list_pokemon(
    _admin_session: Annotated[AdminSession, Depends(require_admin)],
    repository: Annotated[AdminPokemonRepository, Depends(get_admin_repository)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminPokemonPage:
    items, total = repository.list_all(q=q, page=page, page_size=page_size)
    return AdminPokemonPage(
        items=[
            AdminPokemonSummary(
                id=item.id,
                pokedex_number=item.pokedex_number,
                form_key=item.form_key,
                name_zh=item.name_zh,
                name_en=item.name_en,
                generation=item.generation,
                is_active=item.is_active,
            )
            for item in items
        ],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/pokemon/{pokemon_id}", response_model=AdminPokemonDetail, summary="查看寶可夢")
def pokemon_detail(
    pokemon_id: Annotated[int, Path(ge=1)],
    _admin_session: Annotated[AdminSession, Depends(require_admin)],
    repository: Annotated[AdminPokemonRepository, Depends(get_admin_repository)],
) -> AdminPokemonDetail:
    return _detail(_get_or_404(repository, pokemon_id))


@router.get(
    "/pokemon/{pokemon_id}/index-status",
    response_model=AdminIndexStatus,
    summary="查看知識索引狀態",
)
def pokemon_index_status(
    pokemon_id: Annotated[int, Path(ge=1)],
    _admin_session: Annotated[AdminSession, Depends(require_admin)],
    service: Annotated[PokemonReindexService, Depends(get_reindex_service)],
) -> AdminIndexStatus:
    try:
        return _index_status(service.status(pokemon_id))
    except PokemonNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "pokemon_not_found", "message": "找不到指定的寶可夢。"},
        ) from None


@router.post(
    "/pokemon/{pokemon_id}/reindex",
    response_model=AdminReindexJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="將知識向量重建工作加入背景佇列",
)
def reindex_pokemon(
    pokemon_id: Annotated[int, Path(ge=1)],
    _admin_session: Annotated[AdminSession, Depends(require_csrf)],
    repository: Annotated[PokemonReindexJobRepository, Depends(get_reindex_job_repository)],
) -> AdminReindexJobResponse:
    try:
        job, _created = repository.enqueue(pokemon_id)
        repository.session.commit()
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "pokemon_not_found", "message": "找不到指定的寶可夢。"},
        ) from None
    except IntegrityError:
        repository.session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "reindex_job_conflict",
                "message": "此寶可夢已有排隊中或執行中的重建工作。",
            },
        ) from None
    return _job_response(job)


@router.get(
    "/reindex-jobs/{job_id}",
    response_model=AdminReindexJobResponse,
    summary="查看背景索引工作的即時進度",
)
def reindex_job_status(
    request: Request,
    job_id: UUID,
    _admin_session: Annotated[AdminSession, Depends(require_admin)],
    repository: Annotated[PokemonReindexJobRepository, Depends(get_reindex_job_repository)],
    service: Annotated[PokemonReindexService, Depends(get_reindex_service)],
) -> AdminReindexJobResponse:
    job = repository.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "reindex_job_not_found", "message": "找不到指定的重建工作。"},
        )
    index = None
    if job.status in {"succeeded", "failed"}:
        index = _index_status(service.status(job.pokemon_id))
        if job.status == "succeeded":
            _refresh_runtime_profiles(request)
    return _job_response(job, index)


@router.post(
    "/pokemon",
    response_model=AdminPokemonDetail,
    status_code=status.HTTP_201_CREATED,
    summary="新增寶可夢",
)
def create_pokemon(
    payload: AdminPokemonCreate,
    request: Request,
    _admin_session: Annotated[AdminSession, Depends(require_csrf)],
    repository: Annotated[AdminPokemonRepository, Depends(get_admin_repository)],
) -> AdminPokemonDetail:
    try:
        pokemon = repository.create(payload)
        _commit(repository)
    except IntegrityError:
        _rollback_conflict(repository)
    except ValueError as exc:
        repository.session.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_pokemon_data", "message": str(exc)},
        ) from None
    _refresh_runtime_profiles(request)
    return _detail(pokemon)


@router.patch("/pokemon/{pokemon_id}", response_model=AdminPokemonDetail, summary="修改寶可夢")
def update_pokemon(
    payload: AdminPokemonUpdate,
    request: Request,
    pokemon_id: Annotated[int, Path(ge=1)],
    _admin_session: Annotated[AdminSession, Depends(require_csrf)],
    repository: Annotated[AdminPokemonRepository, Depends(get_admin_repository)],
) -> AdminPokemonDetail:
    pokemon = _get_or_404(repository, pokemon_id)
    try:
        pokemon = repository.update(pokemon, payload)
        _commit(repository)
    except IntegrityError:
        _rollback_conflict(repository)
    except ValueError as exc:
        repository.session.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_pokemon_data", "message": str(exc)},
        ) from None
    if "descriptions" not in payload.model_fields_set:
        _refresh_runtime_profiles(request)
    return _detail(pokemon)


@router.post("/pokemon/{pokemon_id}/deactivate", response_model=AdminPokemonDetail, summary="停用寶可夢")
def deactivate_pokemon(
    request: Request,
    pokemon_id: Annotated[int, Path(ge=1)],
    _admin_session: Annotated[AdminSession, Depends(require_csrf)],
    repository: Annotated[AdminPokemonRepository, Depends(get_admin_repository)],
) -> AdminPokemonDetail:
    pokemon = repository.set_active(_get_or_404(repository, pokemon_id), False)
    _commit(repository)
    _refresh_runtime_profiles(request)
    return _detail(pokemon)


@router.post("/pokemon/{pokemon_id}/restore", response_model=AdminPokemonDetail, summary="恢復寶可夢")
def restore_pokemon(
    request: Request,
    pokemon_id: Annotated[int, Path(ge=1)],
    _admin_session: Annotated[AdminSession, Depends(require_csrf)],
    repository: Annotated[AdminPokemonRepository, Depends(get_admin_repository)],
) -> AdminPokemonDetail:
    pokemon = repository.set_active(_get_or_404(repository, pokemon_id), True)
    _commit(repository)
    _refresh_runtime_profiles(request)
    return _detail(pokemon)
