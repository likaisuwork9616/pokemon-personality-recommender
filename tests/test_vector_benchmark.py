import unittest

from scripts.benchmark_vector_search import (
    percentile,
    recall_at_k,
    summarize_latencies,
)


class VectorBenchmarkTests(unittest.TestCase):
    def test_percentile_interpolates_sorted_values(self):
        self.assertEqual(percentile([4, 1, 3, 2], 50), 2.5)
        self.assertAlmostEqual(percentile([1, 2, 3, 4], 95), 3.85)

    def test_latency_summary_reports_percentiles_and_qps(self):
        summary = summarize_latencies([1.0, 2.0, 3.0])

        self.assertEqual(summary.samples, 3)
        self.assertEqual(summary.mean_ms, 2.0)
        self.assertEqual(summary.p50_ms, 2.0)
        self.assertEqual(summary.queries_per_second, 500.0)

    def test_recall_uses_exact_result_as_ground_truth(self):
        self.assertEqual(recall_at_k(["a", "b", "c"], ["a", "c", "x"]), 2 / 3)
        with self.assertRaisesRegex(ValueError, "expected"):
            recall_at_k([], ["a"])


if __name__ == "__main__":
    unittest.main()
