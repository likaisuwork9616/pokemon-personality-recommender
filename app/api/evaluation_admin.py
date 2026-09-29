"""Authenticated collaborative evaluation and label-quality API."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.admin import (
    _record_audit,
    get_admin_audit_repository,
    require_admin,
    require_csrf,
    require_editor,
)
from app.api.deps import get_session
from app.repositories.admin_audit import AdminAuditRepository
from app.repositories.evaluation_admin import (
    EvaluationAnnotationRepository,
    EvaluationCandidateNotFound,
    EvaluationCaseNotFound,
    EvaluationCaseView,
    EvaluationWorkflowError,
)
from app.schemas.evaluation_admin import (
    EvaluationAdjudicationResponse,
    EvaluationAnnotationResponse,
    EvaluationCandidateResponse,
    EvaluationCaseCreate,
    EvaluationCasePage,
    EvaluationCaseResponse,
    EvaluationCaseStatusUpdate,
    EvaluationDatasetExport,
    EvaluationJudgmentBatch,
)
from app.services.admin_auth import AdminSession
from app.services.annotation_quality import build_annotation_quality_report


router = APIRouter(
    prefix="/api/v1/admin/evaluation",
    tags=["evaluation administration"],
)


def get_evaluation_repository(
    session: Annotated[Session, Depends(get_session)],
) -> EvaluationAnnotationRepository:
    return EvaluationAnnotationRepository(session)


def require_adjudicator(
    admin_session: Annotated[AdminSession, Depends(require_csrf)],
) -> AdminSession:
    if admin_session.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "adjudicator_role_required",
                "message": "只有 admin 可以仲裁或發布評估案例。",
            },
        )
    return admin_session


def _case_response(view: EvaluationCaseView) -> EvaluationCaseResponse:
    record = view.case
    return EvaluationCaseResponse(
        id=record.id,
        case_key=record.case_key,
        query=record.query_text,
        segment=record.segment,
        dataset_version=record.dataset_version,
        status=record.status,
        created_by=record.created_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
        candidates=[
            EvaluationCandidateResponse(
                pokemon_id=candidate.pokemon_id,
                pokedex_number=candidate.pokedex_number,
                name_zh=candidate.name_zh,
                display_order=candidate.display_order,
                annotations=[
                    EvaluationAnnotationResponse(
                        annotator=item.annotator_username,
                        grade=item.grade,
                        note=item.note,
                        updated_at=item.updated_at,
                    )
                    for item in candidate.annotations
                ],
                adjudication=(
                    EvaluationAdjudicationResponse(
                        adjudicator=candidate.adjudication.adjudicator_username,
                        grade=candidate.adjudication.grade,
                        note=candidate.adjudication.note,
                        updated_at=candidate.adjudication.updated_at,
                    )
                    if candidate.adjudication is not None
                    else None
                ),
            )
            for candidate in view.candidates
        ],
    )


def _workflow_error(exc: EvaluationWorkflowError) -> HTTPException:
    code = "evaluation_candidate_not_found" if isinstance(
        exc, EvaluationCandidateNotFound
    ) else "evaluation_workflow_conflict"
    status_code = 404 if isinstance(exc, EvaluationCaseNotFound) else 409
    if isinstance(exc, EvaluationCaseNotFound):
        code = "evaluation_case_not_found"
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": str(exc)},
    )


def _commit_with_audit(
    repository: EvaluationAnnotationRepository,
    audit_repository: AdminAuditRepository,
    request: Request,
    admin_session: AdminSession,
    *,
    action: str,
    resource_id: UUID,
) -> None:
    _record_audit(
        audit_repository,
        request,
        admin_session,
        action=action,
        resource_type="evaluation_case",
        resource_id=resource_id,
    )
    try:
        repository.session.commit()
    except IntegrityError:
        repository.session.rollback()
        raise _integrity_conflict() from None


def _integrity_conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "evaluation_conflict",
            "message": "案例代碼或標註版本發生衝突。",
        },
    )


@router.post("/cases", response_model=EvaluationCaseResponse, status_code=201)
def create_case(
    payload: EvaluationCaseCreate,
    request: Request,
    admin_session: Annotated[AdminSession, Depends(require_editor)],
    repository: Annotated[EvaluationAnnotationRepository, Depends(get_evaluation_repository)],
    audit_repository: Annotated[AdminAuditRepository, Depends(get_admin_audit_repository)],
) -> EvaluationCaseResponse:
    try:
        view = repository.create_case(
            case_key=payload.case_key,
            query_text=payload.query,
            segment=payload.segment,
            dataset_version=payload.dataset_version,
            pokemon_ids=payload.pokemon_ids,
            created_by=admin_session.username,
        )
        _commit_with_audit(
            repository,
            audit_repository,
            request,
            admin_session,
            action="evaluation.case.create",
            resource_id=view.case.id,
        )
    except EvaluationWorkflowError as exc:
        repository.session.rollback()
        raise _workflow_error(exc) from None
    except IntegrityError:
        repository.session.rollback()
        raise _integrity_conflict() from None
    return _case_response(repository.get_case(view.case.id))


@router.get("/cases", response_model=EvaluationCasePage)
def list_cases(
    _admin_session: Annotated[AdminSession, Depends(require_admin)],
    repository: Annotated[EvaluationAnnotationRepository, Depends(get_evaluation_repository)],
    status_filter: Annotated[str | None, Query(alias="status", pattern="^(draft|active|retired)$")] = None,
    dataset_version: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> EvaluationCasePage:
    views, total = repository.list_cases(
        page=page,
        page_size=page_size,
        status=status_filter,
        dataset_version=dataset_version,
    )
    return EvaluationCasePage(
        items=[_case_response(view) for view in views],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/cases/{case_id}", response_model=EvaluationCaseResponse)
def get_case(
    case_id: UUID,
    _admin_session: Annotated[AdminSession, Depends(require_admin)],
    repository: Annotated[EvaluationAnnotationRepository, Depends(get_evaluation_repository)],
) -> EvaluationCaseResponse:
    try:
        return _case_response(repository.get_case(case_id))
    except EvaluationWorkflowError as exc:
        raise _workflow_error(exc) from None


@router.put("/cases/{case_id}/annotations", response_model=EvaluationCaseResponse)
def save_annotations(
    case_id: UUID,
    payload: EvaluationJudgmentBatch,
    request: Request,
    admin_session: Annotated[AdminSession, Depends(require_editor)],
    repository: Annotated[EvaluationAnnotationRepository, Depends(get_evaluation_repository)],
    audit_repository: Annotated[AdminAuditRepository, Depends(get_admin_audit_repository)],
) -> EvaluationCaseResponse:
    try:
        repository.save_annotations(
            case_id=case_id,
            annotator=admin_session.username,
            judgments=[
                (item.pokemon_id, item.grade, item.note)
                for item in payload.judgments
            ],
        )
        _commit_with_audit(
            repository,
            audit_repository,
            request,
            admin_session,
            action="evaluation.annotation.upsert",
            resource_id=case_id,
        )
        return _case_response(repository.get_case(case_id))
    except EvaluationWorkflowError as exc:
        repository.session.rollback()
        raise _workflow_error(exc) from None
    except IntegrityError:
        repository.session.rollback()
        raise _integrity_conflict() from None


@router.put("/cases/{case_id}/adjudications", response_model=EvaluationCaseResponse)
def save_adjudications(
    case_id: UUID,
    payload: EvaluationJudgmentBatch,
    request: Request,
    admin_session: Annotated[AdminSession, Depends(require_adjudicator)],
    repository: Annotated[EvaluationAnnotationRepository, Depends(get_evaluation_repository)],
    audit_repository: Annotated[AdminAuditRepository, Depends(get_admin_audit_repository)],
) -> EvaluationCaseResponse:
    try:
        repository.save_adjudications(
            case_id=case_id,
            adjudicator=admin_session.username,
            judgments=[
                (item.pokemon_id, item.grade, item.note)
                for item in payload.judgments
            ],
        )
        _commit_with_audit(
            repository,
            audit_repository,
            request,
            admin_session,
            action="evaluation.adjudication.upsert",
            resource_id=case_id,
        )
        return _case_response(repository.get_case(case_id))
    except EvaluationWorkflowError as exc:
        repository.session.rollback()
        raise _workflow_error(exc) from None
    except IntegrityError:
        repository.session.rollback()
        raise _integrity_conflict() from None


@router.patch("/cases/{case_id}/status", response_model=EvaluationCaseResponse)
def update_status(
    case_id: UUID,
    payload: EvaluationCaseStatusUpdate,
    request: Request,
    admin_session: Annotated[AdminSession, Depends(require_adjudicator)],
    repository: Annotated[EvaluationAnnotationRepository, Depends(get_evaluation_repository)],
    audit_repository: Annotated[AdminAuditRepository, Depends(get_admin_audit_repository)],
) -> EvaluationCaseResponse:
    try:
        repository.set_status(case_id, payload.status)
        _commit_with_audit(
            repository,
            audit_repository,
            request,
            admin_session,
            action=f"evaluation.case.{payload.status}",
            resource_id=case_id,
        )
        return _case_response(repository.get_case(case_id))
    except EvaluationWorkflowError as exc:
        repository.session.rollback()
        raise _workflow_error(exc) from None
    except IntegrityError:
        repository.session.rollback()
        raise _integrity_conflict() from None


@router.get("/quality")
def quality_report(
    _admin_session: Annotated[AdminSession, Depends(require_admin)],
    repository: Annotated[EvaluationAnnotationRepository, Depends(get_evaluation_repository)],
) -> dict[str, object]:
    return build_annotation_quality_report(repository.quality_rows())


@router.get("/export", response_model=EvaluationDatasetExport)
def export_dataset(
    _admin_session: Annotated[AdminSession, Depends(require_admin)],
    repository: Annotated[EvaluationAnnotationRepository, Depends(get_evaluation_repository)],
    dataset_version: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
) -> EvaluationDatasetExport:
    cases: list[dict[str, Any]] = repository.export_active_cases(dataset_version)
    return EvaluationDatasetExport(case_count=len(cases), cases=cases)
