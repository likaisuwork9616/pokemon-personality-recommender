from __future__ import annotations

import unittest

from app.services.reranking import CrossEncoderConfig, CrossEncoderReranker


class _Predictor:
    def __init__(self, scores=None, error=None) -> None:
        self.scores = scores
        self.error = error
        self.calls = []

    def predict(self, pairs, **kwargs):
        self.calls.append((pairs, kwargs))
        if self.error is not None:
            raise self.error
        return self.scores


def _candidate(identifier: int, total: float) -> dict:
    return {
        "database_id": identifier,
        "scores": {"semantic": total, "personality": total, "total": total},
        "matching_evidence": [{"text": f"候選 {identifier} 的人格行為證據"}],
    }


class CrossEncoderRerankerTests(unittest.TestCase):
    def test_bounded_scores_are_blended_and_stably_reranked(self):
        predictor = _Predictor([-3.0, 3.0, 0.0])
        reranker = CrossEncoderReranker(
            CrossEncoderConfig(enabled=True, weight=0.5),
            predictor=predictor,
            clock=iter((1.0, 1.1)).__next__,
        )
        candidates = [_candidate(1, 0.9), _candidate(2, 0.7), _candidate(3, 0.6)]

        outcome = reranker.rerank("安靜守護夥伴", candidates)

        self.assertTrue(outcome.applied)
        self.assertEqual(outcome.reason, "applied")
        self.assertEqual([item["database_id"] for item in outcome.candidates], [2, 3, 1])
        self.assertEqual(outcome.candidates[0]["scores"]["pre_rerank_total"], 0.7)
        self.assertGreater(outcome.candidates[0]["scores"]["reranker"], 0.9)
        self.assertNotIn("reranker", candidates[0]["scores"])
        pairs, kwargs = predictor.calls[0]
        self.assertEqual(pairs[0][0], "安靜守護夥伴")
        self.assertEqual(kwargs, {"batch_size": 10, "show_progress_bar": False})

    def test_latency_budget_and_prediction_failure_keep_base_order(self):
        candidates = [_candidate(1, 0.9), _candidate(2, 0.7), _candidate(3, 0.6)]
        slow = CrossEncoderReranker(
            CrossEncoderConfig(enabled=True, latency_budget_ms=100),
            predictor=_Predictor([0.0, 3.0, 1.0]),
            clock=iter((1.0, 1.2)).__next__,
        )
        failed = CrossEncoderReranker(
            CrossEncoderConfig(enabled=True),
            predictor=_Predictor(error=RuntimeError("model details")),
            clock=iter((2.0, 2.01)).__next__,
        )

        slow_outcome = slow.rerank("query", candidates)
        failed_outcome = failed.rerank("query", candidates)

        self.assertFalse(slow_outcome.applied)
        self.assertEqual(slow_outcome.reason, "latency_budget_exceeded")
        self.assertEqual(list(slow_outcome.candidates), candidates)
        self.assertFalse(failed_outcome.applied)
        self.assertEqual(failed_outcome.reason, "prediction_failed")

    def test_environment_configuration_is_strict_and_disabled_by_default(self):
        self.assertFalse(CrossEncoderConfig.from_env({}).enabled)
        configured = CrossEncoderConfig.from_env({
            "CROSS_ENCODER_ENABLED": "true",
            "CROSS_ENCODER_CANDIDATE_LIMIT": "12",
            "CROSS_ENCODER_WEIGHT": "0.2",
            "CROSS_ENCODER_LATENCY_BUDGET_MS": "400",
        })
        self.assertTrue(configured.enabled)
        self.assertEqual(configured.candidate_limit, 12)
        with self.assertRaises(ValueError):
            CrossEncoderConfig.from_env({"CROSS_ENCODER_ENABLED": "maybe"})
        with self.assertRaises(ValueError):
            CrossEncoderConfig.from_env({"CROSS_ENCODER_CANDIDATE_LIMIT": "2"})


if __name__ == "__main__":
    unittest.main()
