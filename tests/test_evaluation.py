from __future__ import annotations

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.evaluation import EvaluationCase, evaluate_recommendations
from scripts.evaluate_recommendations import load_cases


class _Engine:
    rankings = {
        "one": [1, 4, 3, 2],
        "two": [8, 7, 6, 5],
    }

    def recommend(self, query, top_k=10, *, mbti=None):
        values = self.rankings[query]
        values = (values * 3)[:top_k]
        return [{"pokedex_number": value} for value in values]


class EvaluationTests(unittest.TestCase):
    def test_optional_mbti_is_loaded_normalized_and_passed_to_engine(self):
        payload = {"id": "selected", "query": "個性文字", "mbti": " infp-t ", "relevant_pokedex_numbers": [1]}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            cases = load_cases(path)
        calls = []
        class Engine:
            def recommend(self, query, top_k, *, mbti):
                calls.append((query, top_k, mbti))
                return [{"pokedex_number": number} for number in (1, 2, 3)]
        report = evaluate_recommendations(Engine(), cases, retrieval_k=3)
        self.assertEqual(calls, [("個性文字", 3, "INFP")])
        self.assertNotIn("個性文字", repr(report))
        self.assertNotIn("INFP", repr(report))
        with self.assertRaises(ValueError):
            EvaluationCase("invalid", "one", frozenset({1}), mbti="ABCD")

    def test_report_calculates_retrieval_and_top_three_metrics_without_queries(self):
        cases = [
            EvaluationCase("a", "one", frozenset({1, 2})),
            EvaluationCase("b", "two", frozenset({5})),
        ]
        report = evaluate_recommendations(_Engine(), cases, retrieval_k=4)

        self.assertEqual(report["case_count"], 2)
        self.assertEqual(report["metrics"]["retrieval_recall_at_k"], 1.0)
        self.assertEqual(report["metrics"]["recommendation_hit_rate_at_3"], 0.5)
        self.assertEqual([row["case_id"] for row in report["cases"]], ["a", "b"])
        self.assertNotIn("query", repr(report))

    def test_empty_or_invalid_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_recommendations(_Engine(), [], retrieval_k=10)
        with self.assertRaises(ValueError):
            evaluate_recommendations(_Engine(), [EvaluationCase("a", "one", frozenset({1}))], retrieval_k=2)


if __name__ == "__main__":
    unittest.main()
