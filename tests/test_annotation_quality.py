from __future__ import annotations

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from app.services.annotation_quality import (
    AnnotationQualityRow,
    build_annotation_quality_report,
    quadratic_weighted_kappa,
    query_length_bucket,
)
from scripts.export_evaluation_dataset import write_jsonl


CASE_A = UUID("11111111-1111-1111-1111-111111111111")
CASE_B = UUID("22222222-2222-2222-2222-222222222222")


class AnnotationQualityTests(unittest.TestCase):
    def test_quadratic_weighted_kappa_handles_agreement_and_invalid_alignment(self):
        self.assertEqual(quadratic_weighted_kappa([0, 1, 2, 3], [0, 1, 2, 3]), 1.0)
        self.assertIsNone(quadratic_weighted_kappa([], []))
        self.assertIsNone(quadratic_weighted_kappa([1], [1, 2]))

    def test_report_exposes_conflicts_coverage_pairs_and_slices(self):
        rows = [
            AnnotationQualityRow(CASE_A, "empathy", 25, 1, "alice", 3, 3),
            AnnotationQualityRow(CASE_A, "empathy", 25, 1, "bob", 3, 3),
            AnnotationQualityRow(CASE_A, "empathy", 25, 2, "alice", 0, 1),
            AnnotationQualityRow(CASE_A, "empathy", 25, 2, "bob", 2, 1),
            AnnotationQualityRow(CASE_B, "leadership", 95, 3, "alice", 2, None),
        ]

        report = build_annotation_quality_report(rows)

        self.assertEqual(report["overall"]["case_count"], 2)
        self.assertEqual(report["overall"]["candidate_count"], 3)
        self.assertEqual(report["overall"]["annotator_count"], 2)
        self.assertEqual(report["overall"]["double_annotation_coverage"], 0.666667)
        self.assertEqual(report["overall"]["conflict_rate"], 0.5)
        self.assertEqual(report["overall"]["adjudication_coverage"], 0.666667)
        self.assertEqual(report["annotator_pairs"][0]["common_judgment_count"], 2)
        self.assertEqual(report["slices"]["segment"]["empathy"]["case_count"], 1)
        self.assertEqual(report["slices"]["query_length"]["long"]["candidate_count"], 1)

    def test_query_length_buckets_are_stable(self):
        self.assertEqual(query_length_bucket(39), "short")
        self.assertEqual(query_length_bucket(40), "medium")
        self.assertEqual(query_length_bucket(79), "medium")
        self.assertEqual(query_length_bucket(80), "long")

    def test_versioned_jsonl_export_is_atomic_and_evaluator_compatible(self):
        cases = [
            {
                "id": "listener_v2",
                "query": "我會先聽完大家的想法。",
                "segment": "empathy",
                "dataset_version": "2026.10",
                "relevance": [{"pokedex_number": 25, "grade": 3}],
            }
        ]
        with TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "cases.jsonl"
            write_jsonl(output, cases)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["dataset_version"], "2026.10")
        self.assertEqual(payload["relevance"][0], {"pokedex_number": 25, "grade": 3})


if __name__ == "__main__":
    unittest.main()
