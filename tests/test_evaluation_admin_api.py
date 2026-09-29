from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.admin import get_admin_audit_repository
from app.api.evaluation_admin import get_evaluation_repository
from app.main import create_app
from app.repositories.evaluation_admin import CandidateView, EvaluationCaseView
from app.services.admin_auth import AdminAccount, AdminAuth, AdminAuthConfig
from app.services.annotation_quality import AnnotationQualityRow


CASE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeAuditRepository:
    def __init__(self) -> None:
        self.entries = []

    def record(self, **values):
        self.entries.append(values)


class FakeEvaluationRepository:
    def __init__(self) -> None:
        self.session = FakeSession()
        self.record = None
        self.candidates = []

    def create_case(self, **values):
        now = datetime.now(timezone.utc)
        self.record = SimpleNamespace(
            id=CASE_ID,
            case_key=values["case_key"],
            query_text=values["query_text"],
            segment=values["segment"],
            dataset_version=values["dataset_version"],
            status="draft",
            created_by=values["created_by"],
            created_at=now,
            updated_at=now,
        )
        self.candidates = [
            CandidateView(
                pokemon_id=pokemon_id,
                pokedex_number=pokemon_id,
                name_zh=f"候選 {pokemon_id}",
                display_order=order,
                annotations=(),
                adjudication=None,
            )
            for order, pokemon_id in enumerate(values["pokemon_ids"], start=1)
        ]
        return self.get_case(CASE_ID)

    def get_case(self, _case_id):
        return EvaluationCaseView(case=self.record, candidates=tuple(self.candidates))

    def list_cases(self, **_values):
        return ([self.get_case(CASE_ID)], 1) if self.record else ([], 0)

    def save_annotations(self, *, annotator, judgments, **_values):
        updated = []
        for candidate in self.candidates:
            annotations = list(candidate.annotations)
            for pokemon_id, grade, note in judgments:
                if pokemon_id == candidate.pokemon_id:
                    annotations = [
                        item for item in annotations if item.annotator_username != annotator
                    ]
                    annotations.append(
                        SimpleNamespace(
                            annotator_username=annotator,
                            grade=grade,
                            note=note,
                            updated_at=datetime.now(timezone.utc),
                        )
                    )
            updated.append(
                CandidateView(
                    pokemon_id=candidate.pokemon_id,
                    pokedex_number=candidate.pokedex_number,
                    name_zh=candidate.name_zh,
                    display_order=candidate.display_order,
                    annotations=tuple(annotations),
                    adjudication=candidate.adjudication,
                )
            )
        self.candidates = updated
        return self.get_case(CASE_ID)

    def save_adjudications(self, *, adjudicator, judgments, **_values):
        values = {pokemon_id: (grade, note) for pokemon_id, grade, note in judgments}
        self.candidates = [
            CandidateView(
                pokemon_id=candidate.pokemon_id,
                pokedex_number=candidate.pokedex_number,
                name_zh=candidate.name_zh,
                display_order=candidate.display_order,
                annotations=candidate.annotations,
                adjudication=(
                    SimpleNamespace(
                        adjudicator_username=adjudicator,
                        grade=values[candidate.pokemon_id][0],
                        note=values[candidate.pokemon_id][1],
                        updated_at=datetime.now(timezone.utc),
                    )
                    if candidate.pokemon_id in values
                    else candidate.adjudication
                ),
            )
            for candidate in self.candidates
        ]
        return self.get_case(CASE_ID)

    def set_status(self, _case_id, new_status):
        self.record.status = new_status
        return self.get_case(CASE_ID)

    def quality_rows(self):
        rows = []
        for candidate in self.candidates:
            for annotation in candidate.annotations:
                rows.append(
                    AnnotationQualityRow(
                        CASE_ID,
                        self.record.segment,
                        len(self.record.query_text),
                        candidate.pokemon_id,
                        annotation.annotator_username,
                        annotation.grade,
                        candidate.adjudication.grade if candidate.adjudication else None,
                    )
                )
        return rows

    def export_active_cases(self, _dataset_version=None):
        if not self.record or self.record.status != "active":
            return []
        return [
            {
                "id": self.record.case_key,
                "query": self.record.query_text,
                "segment": self.record.segment,
                "dataset_version": self.record.dataset_version,
                "relevance": [
                    {"pokedex_number": item.pokedex_number, "grade": item.adjudication.grade}
                    for item in self.candidates
                    if item.adjudication and item.adjudication.grade > 0
                ],
            }
        ]


class EvaluationAdminApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeEvaluationRepository()
        self.audit = FakeAuditRepository()
        auth = AdminAuth(
            AdminAuthConfig(
                password="admin-password",
                session_secret="s" * 32,
                accounts=(
                    AdminAccount("viewer", "viewer-password", "viewer"),
                    AdminAccount("alice", "alice-password", "editor"),
                    AdminAccount("bob", "bob-password", "editor"),
                ),
                session_ttl_seconds=600,
            ),
            clock=lambda: 1_700_000_000,
        )
        application = create_app(lambda: SimpleNamespace(), admin_auth=auth)
        application.dependency_overrides[get_evaluation_repository] = lambda: self.repository
        application.dependency_overrides[get_admin_audit_repository] = lambda: self.audit
        self.context = TestClient(application)
        self.client = self.context.__enter__()

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)

    def login(self, username, password):
        response = self.client.post(
            "/api/v1/admin/session",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        return {"X-CSRF-Token": response.json()["csrf_token"]}

    def test_collaborative_annotation_adjudication_quality_and_export(self):
        viewer = self.login("viewer", "viewer-password")
        self.assertEqual(
            self.client.post(
                "/api/v1/admin/evaluation/cases",
                headers=viewer,
                json={
                    "case_key": "patient_listener",
                    "query": "我會先聽完大家的想法再做決定。",
                    "segment": "empathy",
                    "dataset_version": "2026.10",
                    "pokemon_ids": [25, 39],
                },
            ).status_code,
            403,
        )

        alice = self.login("alice", "alice-password")
        created = self.client.post(
            "/api/v1/admin/evaluation/cases",
            headers=alice,
            json={
                "case_key": "patient_listener",
                "query": "我會先聽完大家的想法再做決定。",
                "segment": "empathy",
                "dataset_version": "2026.10",
                "pokemon_ids": [25, 39],
            },
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["status"], "draft")
        judgments = {"judgments": [{"pokemon_id": 25, "grade": 3}, {"pokemon_id": 39, "grade": 0}]}
        self.assertEqual(
            self.client.put(
                f"/api/v1/admin/evaluation/cases/{CASE_ID}/annotations",
                headers=alice,
                json=judgments,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.put(
                f"/api/v1/admin/evaluation/cases/{CASE_ID}/adjudications",
                headers=alice,
                json=judgments,
            ).status_code,
            403,
        )

        bob = self.login("bob", "bob-password")
        bob_judgments = {"judgments": [{"pokemon_id": 25, "grade": 3}, {"pokemon_id": 39, "grade": 1}]}
        self.client.put(
            f"/api/v1/admin/evaluation/cases/{CASE_ID}/annotations",
            headers=bob,
            json=bob_judgments,
        )

        admin = self.login("admin", "admin-password")
        self.assertEqual(
            self.client.put(
                f"/api/v1/admin/evaluation/cases/{CASE_ID}/adjudications",
                headers=admin,
                json=bob_judgments,
            ).status_code,
            200,
        )
        activated = self.client.patch(
            f"/api/v1/admin/evaluation/cases/{CASE_ID}/status",
            headers=admin,
            json={"status": "active"},
        )
        self.assertEqual(activated.json()["status"], "active")

        quality = self.client.get("/api/v1/admin/evaluation/quality").json()
        self.assertEqual(quality["overall"]["double_annotation_coverage"], 1.0)
        self.assertEqual(quality["overall"]["conflict_rate"], 0.5)
        exported = self.client.get("/api/v1/admin/evaluation/export").json()
        self.assertEqual(exported["case_count"], 1)
        self.assertEqual(exported["cases"][0]["relevance"][0]["grade"], 3)
        self.assertEqual(self.repository.session.commits, 5)
        self.assertEqual(len(self.audit.entries), 5)


if __name__ == "__main__":
    unittest.main()
