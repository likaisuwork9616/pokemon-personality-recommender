from __future__ import annotations

import unittest
from types import SimpleNamespace
from uuid import UUID

from app.repositories.evaluation_admin import (
    CandidateView,
    EvaluationAnnotationRepository,
    EvaluationCaseView,
    EvaluationWorkflowError,
)


CASE_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


class FlushSession:
    def __init__(self) -> None:
        self.flushes = 0

    def flush(self) -> None:
        self.flushes += 1


class EvaluationRepositoryRulesTests(unittest.TestCase):
    def view(self, *, annotators, final_grade):
        record = SimpleNamespace(id=CASE_ID, status="draft")
        candidate = CandidateView(
            pokemon_id=25,
            pokedex_number=25,
            name_zh="皮卡丘",
            display_order=1,
            annotations=tuple(
                SimpleNamespace(annotator_username=name) for name in annotators
            ),
            adjudication=(
                SimpleNamespace(grade=final_grade)
                if final_grade is not None
                else None
            ),
        )
        return EvaluationCaseView(record, (candidate,))

    def test_activation_requires_two_annotators_adjudication_and_positive_label(self):
        session = FlushSession()
        repository = EvaluationAnnotationRepository(session)

        repository.get_case = lambda _case_id: self.view(
            annotators=("alice",), final_grade=3
        )
        with self.assertRaisesRegex(EvaluationWorkflowError, "至少兩位標註者"):
            repository.set_status(CASE_ID, "active")

        repository.get_case = lambda _case_id: self.view(
            annotators=("alice", "bob"), final_grade=0
        )
        with self.assertRaisesRegex(EvaluationWorkflowError, "正相關"):
            repository.set_status(CASE_ID, "active")

        complete = self.view(annotators=("alice", "bob"), final_grade=2)
        repository.get_case = lambda _case_id: complete
        activated = repository.set_status(CASE_ID, "active")
        self.assertEqual(activated.case.status, "active")
        self.assertEqual(session.flushes, 1)


if __name__ == "__main__":
    unittest.main()
