from __future__ import annotations

import unittest
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories.recommendation_feedback import FeedbackItemMismatch
from app.services.admin_auth import AdminAuth, AdminAuthConfig
from tests.test_api import FakeEngine


RECOMMENDATION_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


class FakeFeedbackService:
    def __init__(self) -> None:
        self.impressions = []
        self.feedback = []

    def record_impression(self, **values):
        self.impressions.append(values)
        return RECOMMENDATION_ID

    def submit_feedback(self, **values):
        if values["pokemon_id"] not in {1, 2, 3}:
            raise FeedbackItemMismatch("這隻寶可夢不屬於該次推薦結果。")
        created = not any(
            item["pokemon_id"] == values["pokemon_id"] for item in self.feedback
        )
        self.feedback = [
            item for item in self.feedback if item["pokemon_id"] != values["pokemon_id"]
        ]
        self.feedback.append(values)
        return created

    @staticmethod
    def summary():
        return {
            "total_impressions": 10,
            "rated_impressions": 4,
            "response_rate": 0.4,
            "total_feedback": 6,
            "match_rate": 0.5,
            "by_rank": [{"rank": 1, "feedback_count": 4, "match_rate": 0.75}],
            "by_reason": {"no_reason": 3, "personality_mismatch": 3},
            "by_algorithm": [
                {
                    "algorithm_version": "pgvector-fts-rrf-v1",
                    "feedback_count": 6,
                    "match_rate": 0.5,
                }
            ],
        }


class FeedbackApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = FakeFeedbackService()
        auth = AdminAuth(
            AdminAuthConfig(
                password="admin-password",
                session_secret="s" * 32,
                session_ttl_seconds=600,
            ),
            clock=lambda: 1_700_000_000,
        )
        app = create_app(
            FakeEngine,
            admin_auth=auth,
            feedback_service=self.service,
        )
        self.context = TestClient(app)
        self.client = self.context.__enter__()

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)

    def test_recommendation_receipt_and_idempotent_bounded_feedback(self):
        marker = "PRIVATE-FEEDBACK-MARKER"
        recommendation = self.client.post(
            "/api/v1/recommendations",
            json={"text": marker},
        )
        self.assertEqual(recommendation.status_code, 200)
        self.assertEqual(recommendation.json()["recommendation_id"], str(RECOMMENDATION_ID))
        self.assertEqual(
            self.service.impressions,
            [
                {
                    "algorithm_version": "pgvector-fts-rrf-v1",
                    "ranked_pokemon": [(1, 1), (2, 2), (3, 3)],
                }
            ],
        )
        self.assertNotIn(marker, repr(self.service.impressions))

        payload = {
            "recommendation_id": str(RECOMMENDATION_ID),
            "pokemon_id": 1,
            "rank": 1,
            "verdict": "match",
            "reason": "no_reason",
        }
        first = self.client.post("/api/v1/recommendation-feedback", json=payload)
        second = self.client.post("/api/v1/recommendation-feedback", json=payload)
        self.assertEqual(first.json(), {"accepted": True, "created": True})
        self.assertEqual(second.json(), {"accepted": True, "created": False})

        mismatch = self.client.post(
            "/api/v1/recommendation-feedback",
            json={**payload, "pokemon_id": 99},
        )
        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(mismatch.json()["detail"]["code"], "feedback_item_mismatch")

    def test_feedback_payload_is_strict_and_admin_summary_requires_authentication(self):
        invalid = self.client.post(
            "/api/v1/recommendation-feedback",
            json={
                "recommendation_id": str(RECOMMENDATION_ID),
                "pokemon_id": 1,
                "rank": 1,
                "verdict": "match",
                "reason": "personality_mismatch",
                "comment": "free text must not be accepted",
            },
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn("free text must not be accepted", invalid.text)
        self.assertEqual(
            self.client.get("/api/v1/admin/feedback/summary").status_code,
            401,
        )

        login = self.client.post(
            "/api/v1/admin/session",
            json={"username": "admin", "password": "admin-password"},
        )
        self.assertEqual(login.status_code, 200)
        summary = self.client.get("/api/v1/admin/feedback/summary")
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["response_rate"], 0.4)
        self.assertEqual(summary.json()["by_rank"][0]["rank"], 1)


if __name__ == "__main__":
    unittest.main()
