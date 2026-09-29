from __future__ import annotations

import unittest
from types import SimpleNamespace
from uuid import UUID

from app.repositories.recommendation_feedback import (
    FeedbackItemMismatch,
    FeedbackReceiptNotFound,
    RecommendationFeedbackRepository,
)


RECOMMENDATION_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


class FakeSession:
    def __init__(self, scalar_values=(), existing=None) -> None:
        self.scalar_values = list(scalar_values)
        self.existing = existing
        self.added = []

    def scalar(self, _statement):
        return self.scalar_values.pop(0)

    def get(self, _model, _identity):
        return self.existing

    def add(self, value):
        self.added.append(value)


class FeedbackRepositoryTests(unittest.TestCase):
    def test_unknown_receipt_and_non_member_are_distinguished(self):
        unknown = RecommendationFeedbackRepository(
            FakeSession(scalar_values=(None, None))
        )
        with self.assertRaises(FeedbackReceiptNotFound):
            unknown.upsert_feedback(
                recommendation_id=RECOMMENDATION_ID,
                pokemon_id=1,
                rank=1,
                verdict="match",
                reason="no_reason",
            )

        mismatch = RecommendationFeedbackRepository(
            FakeSession(scalar_values=(None, RECOMMENDATION_ID))
        )
        with self.assertRaises(FeedbackItemMismatch):
            mismatch.upsert_feedback(
                recommendation_id=RECOMMENDATION_ID,
                pokemon_id=99,
                rank=1,
                verdict="not_match",
                reason="unfamiliar",
            )

    def test_rank_must_match_receipt_and_existing_feedback_is_updated(self):
        wrong_rank = RecommendationFeedbackRepository(
            FakeSession(scalar_values=(SimpleNamespace(rank=2),))
        )
        with self.assertRaises(FeedbackItemMismatch):
            wrong_rank.upsert_feedback(
                recommendation_id=RECOMMENDATION_ID,
                pokemon_id=1,
                rank=1,
                verdict="match",
                reason="no_reason",
            )

        existing = SimpleNamespace(verdict="match", reason="no_reason")
        session = FakeSession(
            scalar_values=(SimpleNamespace(rank=1),),
            existing=existing,
        )
        created = RecommendationFeedbackRepository(session).upsert_feedback(
            recommendation_id=RECOMMENDATION_ID,
            pokemon_id=1,
            rank=1,
            verdict="not_match",
            reason="ranking",
        )
        self.assertFalse(created)
        self.assertEqual(existing.verdict, "not_match")
        self.assertEqual(existing.reason, "ranking")
        self.assertEqual(session.added, [])


if __name__ == "__main__":
    unittest.main()
