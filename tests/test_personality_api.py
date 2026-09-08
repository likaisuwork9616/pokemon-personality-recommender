from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_personality_repository
from app.api.personality import router
from app.main import create_app
from app.repositories.personality import (
    PERSONALITY_DIMENSIONS,
    PersonalityWeightedTerm,
    PublicPersonalityCatalog,
    PublicPersonalityTrait,
)


def public_catalog() -> PublicPersonalityCatalog:
    return PublicPersonalityCatalog(
        revision=12,
        traits=tuple(
            PublicPersonalityTrait(
                code=f"trait_{index}",
                name_zh=f"特質{index}",
                weighted_terms=(
                    PersonalityWeightedTerm(term=f"詞{index}", weight=2.5),
                ),
            )
            for index in range(PERSONALITY_DIMENSIONS)
        ),
    )


class _Repository:
    def public_catalog(self):
        return public_catalog()


class PublicPersonalityApiTests(unittest.TestCase):
    def setUp(self):
        application = FastAPI()
        application.include_router(router)
        application.dependency_overrides[get_personality_repository] = _Repository
        self.client = TestClient(application)

    def test_public_listing_needs_no_admin_session_and_has_a_narrow_contract(self):
        response = self.client.get("/api/v1/personality/traits")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["revision"], 12)
        self.assertEqual(len(body["traits"]), PERSONALITY_DIMENSIONS)
        self.assertEqual(
            body["traits"][0],
            {
                "code": "trait_0",
                "name_zh": "特質0",
                "weighted_terms": [{"term": "詞0", "weight": 2.5}],
            },
        )
        self.assertEqual(body["type_weight_version"], "type-persona-v1")
        self.assertEqual(body["type_profile_count"], 18)
        self.assertNotIn("type_profiles", body)
        serialized = response.text
        for private_field in (
            "language_code",
            "normalized_term",
            "vector_index",
            "is_active",
        ):
            self.assertNotIn(private_field, serialized)
        self.assertEqual(
            response.headers["etag"],
            '"personality-v12-type-persona-v1"',
        )
        self.assertEqual(response.headers["cache-control"], "public, max-age=60")

    def test_invalid_repository_snapshot_is_a_sanitized_503(self):
        private_marker = "PRIVATE-VOCABULARY-FAILURE"

        class BrokenRepository:
            def public_catalog(self):
                raise RuntimeError(private_marker)

        application = FastAPI()
        application.include_router(router)
        application.dependency_overrides[get_personality_repository] = BrokenRepository
        response = TestClient(application).get("/api/v1/personality/traits")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"]["code"],
            "personality_catalog_unavailable",
        )
        self.assertNotIn(private_marker, response.text)

    def test_main_application_exposes_the_public_route(self):
        paths = create_app(lambda: object()).openapi()["paths"]

        self.assertIn("/api/v1/personality/traits", paths)


if __name__ == "__main__":
    unittest.main()
