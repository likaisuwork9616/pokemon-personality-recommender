import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.recommendation import RetrievalUnavailableError


class FakeEngine:
    def __init__(self):
        self.explain_calls = 0

    def recommend(self, text, top_k=3):
        return [
            {
                "rank": rank,
                "pokedex_number": rank,
                "name": f"寶可夢{rank}",
                "name_en": f"Pokemon {rank}",
                "type": "一般",
                "img": "",
                "scores": {
                    "semantic": 0.8,
                    "personality": 0.7,
                    "total": 0.75,
                },
                "matching_evidence": [
                    {
                        "source": "analysis_text",
                        "text": "重視夥伴",
                        "matched_traits": ["守護型人格"],
                    }
                ],
            }
            for rank in range(1, top_k + 1)
        ]

    def explain(self, text, pokemon):
        self.explain_calls += 1
        return f"推薦 {pokemon['name']}"


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine()
        self.context = TestClient(create_app(lambda: self.engine))
        self.client = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def test_contract_returns_top_three_without_explanation(self):
        response = self.client.post(
            "/api/v1/recommendations",
            json={"text": "我重視朋友"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 3)
        self.assertEqual(response.json()["algorithm_version"], "pgvector-fts-rrf-v1")
        self.assertEqual(self.engine.explain_calls, 0)

    def test_explanation_is_opt_in(self):
        response = self.client.post(
            "/api/v1/recommendations",
            json={"text": "我重視朋友", "generate_explanation": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.engine.explain_calls, 3)

    def test_validation_and_openapi(self):
        self.assertEqual(
            self.client.post(
                "/api/v1/recommendations",
                json={"text": ""},
            ).status_code,
            422,
        )
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/api/v1/recommendations", schema["paths"])
        self.assertTrue(schema["paths"]["/recommend"]["post"]["deprecated"])

    def test_health(self):
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        self.assertEqual(
            self.client.get("/health/ready").json(),
            {"status": "ready"},
        )

    def test_retrieval_unavailable_maps_to_503(self):
        def unavailable(*_args, **_kwargs):
            raise RetrievalUnavailableError("索引不足")

        self.engine.recommend = unavailable
        response = self.client.post(
            "/api/v1/recommendations",
            json={"text": "我重視朋友"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "retrieval_unavailable")


class UnreadyApplicationTests(unittest.TestCase):
    def test_factory_failure_keeps_liveness_but_fails_readiness(self):
        def broken_factory():
            raise RuntimeError("synthetic startup failure")

        with TestClient(create_app(broken_factory)) as client:
            self.assertEqual(client.get("/health/live").status_code, 200)
            self.assertEqual(client.get("/health/ready").status_code, 503)
            response = client.post(
                "/api/v1/recommendations",
                json={"text": "我重視朋友"},
            )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                response.json()["detail"]["code"],
                "service_not_ready",
            )


if __name__ == "__main__":
    unittest.main()
