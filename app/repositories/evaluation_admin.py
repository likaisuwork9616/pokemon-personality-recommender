"""Persistence for collaborative recommendation evaluation labels."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    EvaluationAdjudication,
    EvaluationAnnotation,
    EvaluationCandidate,
    EvaluationCaseRecord,
    Pokemon,
)
from app.services.annotation_quality import AnnotationQualityRow


@dataclass(frozen=True)
class CandidateView:
    pokemon_id: int
    pokedex_number: int
    name_zh: str
    display_order: int
    annotations: tuple[EvaluationAnnotation, ...]
    adjudication: EvaluationAdjudication | None


@dataclass(frozen=True)
class EvaluationCaseView:
    case: EvaluationCaseRecord
    candidates: tuple[CandidateView, ...]


class EvaluationWorkflowError(ValueError):
    pass


class EvaluationCaseNotFound(EvaluationWorkflowError):
    pass


class EvaluationCandidateNotFound(EvaluationWorkflowError):
    pass


class EvaluationAnnotationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_case(
        self,
        *,
        case_key: str,
        query_text: str,
        segment: str,
        dataset_version: str,
        pokemon_ids: list[int],
        created_by: str,
    ) -> EvaluationCaseView:
        pokemon = list(
            self.session.scalars(
                select(Pokemon).where(
                    Pokemon.id.in_(pokemon_ids),
                    Pokemon.is_active.is_(True),
                )
            )
        )
        if {item.id for item in pokemon} != set(pokemon_ids):
            raise EvaluationCandidateNotFound(
                "候選寶可夢不存在或已停用。"
            )
        record = EvaluationCaseRecord(
            id=uuid4(),
            case_key=case_key,
            query_text=query_text,
            segment=segment,
            dataset_version=dataset_version,
            status="draft",
            created_by=created_by,
        )
        self.session.add(record)
        for order, pokemon_id in enumerate(pokemon_ids, start=1):
            self.session.add(
                EvaluationCandidate(
                    case_id=record.id,
                    pokemon_id=pokemon_id,
                    display_order=order,
                )
            )
        self.session.flush()
        return self.get_case(record.id)

    def list_cases(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        dataset_version: str | None = None,
    ) -> tuple[list[EvaluationCaseView], int]:
        filters = []
        if status:
            filters.append(EvaluationCaseRecord.status == status)
        if dataset_version:
            filters.append(EvaluationCaseRecord.dataset_version == dataset_version)
        total = int(
            self.session.scalar(
                select(func.count()).select_from(EvaluationCaseRecord).where(*filters)
            )
            or 0
        )
        case_ids = list(
            self.session.scalars(
                select(EvaluationCaseRecord.id)
                .where(*filters)
                .order_by(
                    EvaluationCaseRecord.updated_at.desc(),
                    EvaluationCaseRecord.case_key,
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return [self.get_case(case_id) for case_id in case_ids], total

    def get_case(self, case_id: UUID) -> EvaluationCaseView:
        record = self.session.get(EvaluationCaseRecord, case_id)
        if record is None:
            raise EvaluationCaseNotFound("找不到指定的評估案例。")
        candidate_rows = self.session.execute(
            select(EvaluationCandidate, Pokemon)
            .join(Pokemon, Pokemon.id == EvaluationCandidate.pokemon_id)
            .where(EvaluationCandidate.case_id == case_id)
            .order_by(EvaluationCandidate.display_order)
        ).all()
        annotations = list(
            self.session.scalars(
                select(EvaluationAnnotation)
                .where(EvaluationAnnotation.case_id == case_id)
                .order_by(
                    EvaluationAnnotation.pokemon_id,
                    EvaluationAnnotation.annotator_username,
                )
            )
        )
        adjudications = list(
            self.session.scalars(
                select(EvaluationAdjudication).where(
                    EvaluationAdjudication.case_id == case_id
                )
            )
        )
        annotations_by_pokemon: dict[int, list[EvaluationAnnotation]] = {}
        for annotation in annotations:
            annotations_by_pokemon.setdefault(annotation.pokemon_id, []).append(annotation)
        adjudication_by_pokemon = {
            item.pokemon_id: item for item in adjudications
        }
        return EvaluationCaseView(
            case=record,
            candidates=tuple(
                CandidateView(
                    pokemon_id=pokemon.id,
                    pokedex_number=pokemon.pokedex_number,
                    name_zh=pokemon.name_zh,
                    display_order=candidate.display_order,
                    annotations=tuple(annotations_by_pokemon.get(pokemon.id, ())),
                    adjudication=adjudication_by_pokemon.get(pokemon.id),
                )
                for candidate, pokemon in candidate_rows
            ),
        )

    def save_annotations(
        self,
        *,
        case_id: UUID,
        annotator: str,
        judgments: list[tuple[int, int, str | None]],
    ) -> EvaluationCaseView:
        view = self.get_case(case_id)
        candidate_ids = {candidate.pokemon_id for candidate in view.candidates}
        if not {pokemon_id for pokemon_id, _grade, _note in judgments} <= candidate_ids:
            raise EvaluationCandidateNotFound("評分包含不屬於此案例的候選寶可夢。")
        existing = {
            item.pokemon_id: item
            for item in self.session.scalars(
                select(EvaluationAnnotation).where(
                    EvaluationAnnotation.case_id == case_id,
                    EvaluationAnnotation.annotator_username == annotator,
                )
            )
        }
        for pokemon_id, grade, note in judgments:
            item = existing.get(pokemon_id)
            if item is None:
                self.session.add(
                    EvaluationAnnotation(
                        case_id=case_id,
                        pokemon_id=pokemon_id,
                        annotator_username=annotator,
                        grade=grade,
                        note=note,
                    )
                )
            else:
                item.grade = grade
                item.note = note
        self.session.flush()
        return self.get_case(case_id)

    def save_adjudications(
        self,
        *,
        case_id: UUID,
        adjudicator: str,
        judgments: list[tuple[int, int, str | None]],
    ) -> EvaluationCaseView:
        view = self.get_case(case_id)
        candidate_ids = {candidate.pokemon_id for candidate in view.candidates}
        if not {pokemon_id for pokemon_id, _grade, _note in judgments} <= candidate_ids:
            raise EvaluationCandidateNotFound("仲裁包含不屬於此案例的候選寶可夢。")
        existing = {
            item.pokemon_id: item
            for item in self.session.scalars(
                select(EvaluationAdjudication).where(
                    EvaluationAdjudication.case_id == case_id
                )
            )
        }
        for pokemon_id, grade, note in judgments:
            item = existing.get(pokemon_id)
            if item is None:
                self.session.add(
                    EvaluationAdjudication(
                        case_id=case_id,
                        pokemon_id=pokemon_id,
                        grade=grade,
                        adjudicator_username=adjudicator,
                        note=note,
                    )
                )
            else:
                item.grade = grade
                item.adjudicator_username = adjudicator
                item.note = note
        self.session.flush()
        return self.get_case(case_id)

    def set_status(self, case_id: UUID, new_status: str) -> EvaluationCaseView:
        view = self.get_case(case_id)
        if new_status == "active":
            incomplete = [
                candidate
                for candidate in view.candidates
                if len({item.annotator_username for item in candidate.annotations}) < 2
                or candidate.adjudication is None
            ]
            if incomplete:
                raise EvaluationWorkflowError(
                    "案例啟用前，每個候選都需要至少兩位標註者與一筆仲裁。"
                )
            if not any(
                candidate.adjudication and candidate.adjudication.grade > 0
                for candidate in view.candidates
            ):
                raise EvaluationWorkflowError("案例至少需要一筆正相關仲裁標籤。")
        view.case.status = new_status
        self.session.flush()
        return self.get_case(case_id)

    def quality_rows(self) -> list[AnnotationQualityRow]:
        views, _total = self.list_cases(page=1, page_size=10_000)
        rows: list[AnnotationQualityRow] = []
        for view in views:
            for candidate in view.candidates:
                if not candidate.annotations:
                    rows.append(
                        AnnotationQualityRow(
                            case_id=view.case.id,
                            segment=view.case.segment,
                            query_length=len(view.case.query_text.strip()),
                            pokemon_id=candidate.pokemon_id,
                            final_grade=(
                                candidate.adjudication.grade
                                if candidate.adjudication is not None
                                else None
                            ),
                        )
                    )
                for annotation in candidate.annotations:
                    rows.append(
                        AnnotationQualityRow(
                            case_id=view.case.id,
                            segment=view.case.segment,
                            query_length=len(view.case.query_text.strip()),
                            pokemon_id=candidate.pokemon_id,
                            annotator=annotation.annotator_username,
                            grade=annotation.grade,
                            final_grade=(
                                candidate.adjudication.grade
                                if candidate.adjudication is not None
                                else None
                            ),
                        )
                    )
        return rows

    def export_active_cases(self, dataset_version: str | None = None) -> list[dict[str, object]]:
        views, _total = self.list_cases(
            page=1,
            page_size=10_000,
            status="active",
            dataset_version=dataset_version,
        )
        exported = []
        for view in sorted(views, key=lambda item: item.case.case_key):
            relevance = [
                {
                    "pokedex_number": candidate.pokedex_number,
                    "grade": candidate.adjudication.grade,
                }
                for candidate in view.candidates
                if candidate.adjudication is not None
                and candidate.adjudication.grade > 0
            ]
            if relevance:
                exported.append(
                    {
                        "id": view.case.case_key,
                        "query": view.case.query_text,
                        "segment": view.case.segment,
                        "dataset_version": view.case.dataset_version,
                        "relevance": relevance,
                    }
                )
        return exported
