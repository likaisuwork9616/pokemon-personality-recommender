from __future__ import annotations

import unittest

from app.services.recommendation_feedback import RecommendationFeedbackService


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def commit(self) -> None:
        self.commits += 1


class CaptureRepository:
    def __init__(self, session, calls) -> None:
        self.session = session
        self.calls = calls

    def create_impression(self, **values):
        self.calls.append(("impression", values))

    def upsert_feedback(self, **values):
        self.calls.append(("feedback", values))
        return True

    def summary(self):
        return {"total_impressions": 0}


class FeedbackServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.calls = []
        self.service = RecommendationFeedbackService(
            lambda: self.session,
            repository_factory=lambda session: CaptureRepository(session, self.calls),
        )

    def test_receipt_only_receives_algorithm_and_ranked_ids(self):
        receipt = self.service.record_impression(
            algorithm_version="pgvector-fts-rrf-v1",
            ranked_pokemon=[(1, 11), (2, 22), (3, 33)],
        )

        self.assertIsNotNone(receipt)
        values = self.calls[0][1]
        self.assertEqual(values["ranked_pokemon"], [(1, 11), (2, 22), (3, 33)])
        self.assertFalse(any("query" in key for key in values))
        self.assertEqual(self.session.commits, 1)

    def test_receipt_rejects_wrong_ranks_or_duplicate_pokemon(self):
        with self.assertRaises(ValueError):
            self.service.record_impression(
                algorithm_version="v1",
                ranked_pokemon=[(1, 11), (3, 22), (2, 33)],
            )
        with self.assertRaises(ValueError):
            self.service.record_impression(
                algorithm_version="v1",
                ranked_pokemon=[(1, 11), (2, 11), (3, 33)],
            )

    def test_feedback_is_committed_as_bounded_fields(self):
        created = self.service.submit_feedback(
            recommendation_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            pokemon_id=11,
            rank=1,
            verdict="not_match",
            reason="ranking",
        )
        self.assertTrue(created)
        self.assertEqual(self.calls[0][0], "feedback")
        self.assertEqual(self.calls[0][1]["reason"], "ranking")
        self.assertEqual(self.session.commits, 1)


if __name__ == "__main__":
    unittest.main()
