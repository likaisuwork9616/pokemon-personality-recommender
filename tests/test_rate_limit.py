from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.rate_limit import (
    RecommendationAbuseGuard,
    RecommendationRateLimitConfig,
)
from tests.test_api import FakeEngine


class _Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


class RecommendationAbuseGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = _Clock()
        self.config = RecommendationRateLimitConfig(
            recommendation_window_seconds=60,
            explanation_window_seconds=600,
            recommendations_per_client=2,
            explanations_per_client=1,
            explanations_global=2,
            max_tracked_clients=100,
        )
        self.guard = RecommendationAbuseGuard(
            self.config,
            clock=self.clock,
            hash_key=b"test-rate-limit-key",
        )

    def test_per_client_recommendation_limit_resets_after_window(self):
        self.assertTrue(
            self.guard.check("client-a", explanation_requested=False).allowed
        )
        self.assertTrue(
            self.guard.check("client-a", explanation_requested=False).allowed
        )
        denied = self.guard.check("client-a", explanation_requested=False)

        self.assertFalse(denied.allowed)
        self.assertEqual(denied.retry_after_seconds, 60)
        self.clock.value += 61
        self.assertTrue(
            self.guard.check("client-a", explanation_requested=False).allowed
        )

    def test_explanation_has_per_client_and_global_budgets(self):
        self.assertTrue(
            self.guard.check("client-a", explanation_requested=True).allowed
        )
        self.assertFalse(
            self.guard.check("client-a", explanation_requested=True).allowed
        )
        self.assertTrue(
            self.guard.check("client-b", explanation_requested=True).allowed
        )
        denied = self.guard.check("client-c", explanation_requested=True)

        self.assertFalse(denied.allowed)
        self.assertEqual(denied.scope, "global_explanations")

    def test_client_identity_is_not_stored_in_plain_text(self):
        marker = "203.0.113.55"
        self.guard.check(marker, explanation_requested=False)

        self.assertNotIn(marker, repr(self.guard._clients))


class RecommendationRateLimitApiTests(unittest.TestCase):
    def test_endpoint_returns_429_and_retry_after(self):
        guard = RecommendationAbuseGuard(
            RecommendationRateLimitConfig(
                recommendation_window_seconds=60,
                explanation_window_seconds=600,
                recommendations_per_client=1,
                explanations_per_client=1,
                explanations_global=1,
                max_tracked_clients=100,
            ),
            hash_key=b"test-rate-limit-key",
        )
        with TestClient(
            create_app(
                FakeEngine,
                recommendation_abuse_guard=guard,
            )
        ) as client:
            first = client.post(
                "/api/v1/recommendations",
                json={"text": "我重視朋友"},
            )
            limited = client.post(
                "/api/v1/recommendations",
                json={"text": "我重視朋友"},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["X-RateLimit-Remaining"], "0")
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(
            limited.json()["detail"]["code"],
            "recommendation_rate_limited",
        )
        self.assertEqual(limited.headers["X-RateLimit-Remaining"], "0")
        self.assertGreaterEqual(int(limited.headers["Retry-After"]), 1)


if __name__ == "__main__":
    unittest.main()
