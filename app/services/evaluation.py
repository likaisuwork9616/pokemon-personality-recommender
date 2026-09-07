"""Offline, label-based retrieval and Top-3 recommendation evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from math import log2
from statistics import mean, median
from time import perf_counter
from typing import Any, Iterable


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    query: str
    relevant_pokedex_numbers: frozenset[int]


def _reciprocal_rank(ranked: list[int], relevant: frozenset[int]) -> float:
    return next((1.0 / rank for rank, value in enumerate(ranked, start=1) if value in relevant), 0.0)


def _ndcg(ranked: list[int], relevant: frozenset[int]) -> float:
    dcg = sum(1.0 / log2(rank + 1) for rank, value in enumerate(ranked, start=1) if value in relevant)
    ideal_hits = min(len(ranked), len(relevant))
    ideal = sum(1.0 / log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / ideal if ideal else 0.0


def evaluate_recommendations(engine: Any, cases: Iterable[EvaluationCase], *, retrieval_k: int = 10) -> dict[str, Any]:
    if not 3 <= retrieval_k <= 10:
        raise ValueError("retrieval_k must be between 3 and 10")
    rows = []
    latencies = []
    for case in cases:
        if not case.case_id or not case.query.strip() or not case.relevant_pokedex_numbers:
            raise ValueError("every evaluation case needs an id, query and relevance labels")
        started = perf_counter()
        results = engine.recommend(case.query, top_k=retrieval_k)
        latencies.append((perf_counter() - started) * 1000.0)
        ranked = [int(item["pokedex_number"]) for item in results]
        top3 = ranked[:3]
        retrieval_hits = sum(item in case.relevant_pokedex_numbers for item in ranked)
        rows.append({
            "case_id": case.case_id,
            "retrieval_recall_at_k": retrieval_hits / len(case.relevant_pokedex_numbers),
            "retrieval_mrr_at_k": _reciprocal_rank(ranked, case.relevant_pokedex_numbers),
            "retrieval_ndcg_at_k": _ndcg(ranked, case.relevant_pokedex_numbers),
            "recommendation_hit_rate_at_3": float(any(item in case.relevant_pokedex_numbers for item in top3)),
            "recommendation_precision_at_3": sum(item in case.relevant_pokedex_numbers for item in top3) / 3.0,
            "recommendation_mrr_at_3": _reciprocal_rank(top3, case.relevant_pokedex_numbers),
        })
    if not rows:
        raise ValueError("at least one evaluation case is required")
    metric_names = [key for key in rows[0] if key != "case_id"]
    return {
        "case_count": len(rows),
        "retrieval_k": retrieval_k,
        "metrics": {name: round(mean(row[name] for row in rows), 6) for name in metric_names},
        "latency_ms": {
            "mean": round(mean(latencies), 4),
            "p50": round(median(latencies), 4),
            "max": round(max(latencies), 4),
        },
        "cases": rows,
    }
