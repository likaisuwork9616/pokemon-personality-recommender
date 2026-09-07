from __future__ import annotations

import unittest

from app.services.evaluation import EvaluationCase, evaluate_recommendations


class _Engine:
    rankings = {
        "one": [1, 4, 3, 2],
        "two": [8, 7, 6, 5],
    }

    def recommend(self, query, top_k=10):
        values = self.rankings[query]
        values = (values * 3)[:top_k]
        return [{"pokedex_number": value} for value in values]


class EvaluationTests(unittest.TestCase):
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
