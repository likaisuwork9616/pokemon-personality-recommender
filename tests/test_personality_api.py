from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.personality import router
from app.main import create_app
from app.services.mbti_catalog import MBTI_CODES, get_mbti_catalog


class PublicPersonalityApiTests(unittest.TestCase):
    def setUp(self):
        application = FastAPI()
        application.include_router(router)
        self.client = TestClient(application)

    def test_public_listing_is_bundled_detailed_and_needs_no_database(self):
        with patch("app.db.session.get_session_factory", side_effect=AssertionError("DB forbidden")):
            response = self.client.get("/api/v1/personality/traits")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        catalog = get_mbti_catalog()
        self.assertEqual(body["revision"], catalog.revision)
        self.assertEqual(body["catalog_version"], catalog.version)
        self.assertEqual(body["source"], "bundled")
        self.assertEqual(tuple(item["code"] for item in body["traits"]), MBTI_CODES)
        for profile in body["traits"]:
            for key in ("summary", "information_style", "decision_style", "interaction_style", "action_style", "strengths", "blind_spots", "stress_pattern", "growth_tips", "weighted_terms", "source_urls", "reviewed_at"):
                self.assertTrue(profile[key], (profile["code"], key))
        for legacy in ("type_weight_version", "type_profile_count", "vector_index", "normalized_term"):
            self.assertNotIn(legacy, response.text)
        self.assertIn(catalog.content_hash[:16], response.headers["etag"])
        self.assertEqual(response.headers["cache-control"], "public, max-age=60")

    def test_invalid_snapshot_is_a_sanitized_503(self):
        with patch("app.api.personality.get_mbti_catalog", side_effect=RuntimeError("PRIVATE-FAILURE")):
            response = self.client.get("/api/v1/personality/traits")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "personality_catalog_unavailable")
        self.assertNotIn("PRIVATE-FAILURE", response.text)

    def test_main_application_exposes_public_route(self):
        self.assertIn("/api/v1/personality/traits", create_app(lambda: object()).openapi()["paths"])


if __name__ == "__main__":
    unittest.main()
