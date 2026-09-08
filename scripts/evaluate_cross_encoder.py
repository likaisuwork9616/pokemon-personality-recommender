"""Compare baseline ranking with the optional multilingual Cross-Encoder."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import _default_engine_factory
from app.services.evaluation import evaluate_recommendations
from app.services.reranking import (
    DEFAULT_CROSS_ENCODER_MODEL,
    CrossEncoderConfig,
    CrossEncoderReranker,
)
from scripts.evaluate_recommendations import load_cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluation" / "recommendation_cases.jsonl")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default=DEFAULT_CROSS_ENCODER_MODEL)
    parser.add_argument("--retrieval-k", type=int, default=10)
    parser.add_argument("--candidate-limit", type=int, default=10)
    parser.add_argument("--weight", type=float, default=0.25)
    parser.add_argument("--max-added-p95-ms", type=float, default=250.0)
    parser.add_argument("--inference-timeout-ms", type=float, default=5000.0)
    parser.add_argument("--min-ndcg-improvement", type=float, default=0.001)
    parser.add_argument("--warmup", type=int, default=1)
    args = parser.parse_args()
    if args.warmup < 0:
        parser.error("--warmup must not be negative")

    cases = load_cases(args.dataset)
    engine = _default_engine_factory()
    engine.reranker = None
    baseline = evaluate_recommendations(engine, cases, retrieval_k=args.retrieval_k)

    config = CrossEncoderConfig(
        enabled=True,
        model_name=args.model,
        candidate_limit=args.candidate_limit,
        weight=args.weight,
        # Keep the experiment's quality measurement independent from the
        # deployment acceptance threshold. Runtime still uses its stricter
        # CROSS_ENCODER_LATENCY_BUDGET_MS fallback.
        latency_budget_ms=args.inference_timeout_ms,
        batch_size=args.candidate_limit,
    )
    engine.reranker = CrossEncoderReranker(config)
    for _ in range(args.warmup):
        engine.recommend(cases[0].query, top_k=args.retrieval_k)
    treatment = evaluate_recommendations(engine, cases, retrieval_k=args.retrieval_k)

    ndcg_delta = (
        treatment["metrics"]["retrieval_ndcg_at_k"]
        - baseline["metrics"]["retrieval_ndcg_at_k"]
    )
    added_p95 = treatment["latency_ms"]["p95"] - baseline["latency_ms"]["p95"]
    quality_accepted = ndcg_delta >= args.min_ndcg_improvement
    latency_accepted = added_p95 <= args.max_added_p95_ms
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": args.model,
        "candidate_limit": args.candidate_limit,
        "weight": args.weight,
        "thresholds": {
            "min_ndcg_improvement": args.min_ndcg_improvement,
            "max_added_p95_ms": args.max_added_p95_ms,
            "inference_timeout_ms": args.inference_timeout_ms,
        },
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or platform.machine(),
            "python": platform.python_version(),
        },
        "baseline": baseline,
        "cross_encoder": treatment,
        "comparison": {
            "retrieval_ndcg_at_k_delta": round(ndcg_delta, 6),
            "added_p95_ms": round(added_p95, 4),
            "quality_accepted": quality_accepted,
            "latency_accepted": latency_accepted,
            "accepted": quality_accepted and latency_accepted,
        },
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return int(not report["comparison"]["accepted"])


if __name__ == "__main__":
    raise SystemExit(main())
