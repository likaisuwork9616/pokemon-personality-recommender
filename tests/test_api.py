import unittest
from fastapi.testclient import TestClient
from app.main import create_app

class FakeEngine:
    def __init__(self): self.explain_calls = 0
    def recommend(self, text, top_k=3):
        return [{"rank": rank, "pokedex_number": rank, "name": f"寶可夢{rank}", "name_en": f"Pokemon {rank}", "type": "一般", "img": "", "scores": {"semantic": .8, "personality": .7, "total": .75}, "matching_evidence": [{"source": "analysis_text", "text": "重視夥伴", "matched_traits": ["守護型人格"]}]} for rank in range(1, top_k + 1)]
    def explain(self, text, pokemon): self.explain_calls += 1; return f"推薦 {pokemon['name']}"

class ApiTests(unittest.TestCase):
    def setUp(self): self.engine = FakeEngine(); self.context = TestClient(create_app(lambda: self.engine)); self.client = self.context.__enter__()
    def tearDown(self): self.context.__exit__(None, None, None)
    def test_contract_returns_top_three_without_explanation(self):
        response = self.client.post("/api/v1/recommendations", json={"text": "我重視朋友"}); self.assertEqual(response.status_code, 200); self.assertEqual(len(response.json()["results"]), 3); self.assertEqual(self.engine.explain_calls, 0)
    def test_explanation_is_opt_in(self):
        response = self.client.post("/api/v1/recommendations", json={"text": "我重視朋友", "generate_explanation": True}); self.assertEqual(response.status_code, 200); self.assertEqual(self.engine.explain_calls, 3)
    def test_validation_and_openapi(self):
        self.assertEqual(self.client.post("/api/v1/recommendations", json={"text": ""}).status_code, 422); schema = self.client.get("/openapi.json").json(); self.assertIn("/api/v1/recommendations", schema["paths"]); self.assertTrue(schema["paths"]["/recommend"]["post"]["deprecated"])
    def test_health(self): self.assertEqual(self.client.get("/health/live").status_code, 200); self.assertEqual(self.client.get("/health/ready").json(), {"status": "ready"})

if __name__ == "__main__": unittest.main()
