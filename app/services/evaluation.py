"""Offline, label-based retrieval and Top-3 recommendation evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from math import log2
from statistics import mean, median
from time import perf_counter
from typing import Any, Iterable, Mapping


MIN_RELEVANCE_GRADE = 1
MAX_RELEVANCE_GRADE = 3
HIGH_RELEVANCE_GRADE = 2
RELEVANCE_LEVELS = {
    1: "部分相關",
    2: "高度相關",
    3: "核心標註",
}


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    query: str
    relevance_judgments: Mapping[int, int] | Iterable[int]

    def __post_init__(self) -> None:
        raw = self.relevance_judgments
        judgments = (
            {int(number): int(grade) for number, grade in raw.items()}
            if isinstance(raw, Mapping)
            else {int(number): MIN_RELEVANCE_GRADE for number in raw}
        )
        if not judgments:
            raise ValueError("every evaluation case needs relevance judgments")
        if any(
            grade < MIN_RELEVANCE_GRADE or grade > MAX_RELEVANCE_GRADE
            for grade in judgments.values()
        ):
            raise ValueError(
                f"relevance grades must be between {MIN_RELEVANCE_GRADE} "
                f"and {MAX_RELEVANCE_GRADE}"
            )
        object.__setattr__(self, "relevance_judgments", judgments)

    @property
    def relevant_pokedex_numbers(self) -> frozenset[int]:
        """Compatibility view for callers that only need binary relevance."""

        return frozenset(self.relevance_judgments)


def _reciprocal_rank(ranked: list[int], relevant: frozenset[int]) -> float:
    return next((1.0 / rank for rank, value in enumerate(ranked, start=1) if value in relevant), 0.0)


def _ndcg(ranked: list[int], judgments: Mapping[int, int]) -> float:
    dcg = sum(
        (2.0 ** judgments.get(value, 0) - 1.0) / log2(rank + 1)
        for rank, value in enumerate(ranked, start=1)
    )
    ideal_grades = sorted(judgments.values(), reverse=True)[: len(ranked)]
    ideal = sum(
        (2.0**grade - 1.0) / log2(rank + 1)
        for rank, grade in enumerate(ideal_grades, start=1)
    )
    return dcg / ideal if ideal else 0.0


def evaluate_recommendations(engine: Any, cases: Iterable[EvaluationCase], *, retrieval_k: int = 10) -> dict[str, Any]:
    if not 3 <= retrieval_k <= 10:
        raise ValueError("retrieval_k must be between 3 and 10")
    rows = []
    latencies = []
    for case in cases:
        if not case.case_id or not case.query.strip() or not case.relevance_judgments:
            raise ValueError("every evaluation case needs an id, query and relevance labels")
        started = perf_counter()
        results = engine.recommend(case.query, top_k=retrieval_k)
        latencies.append((perf_counter() - started) * 1000.0)
        ranked = [int(item["pokedex_number"]) for item in results]
        top3 = ranked[:3]
        relevant = case.relevant_pokedex_numbers
        highly_relevant = frozenset(
            number
            for number, grade in case.relevance_judgments.items()
            if grade >= HIGH_RELEVANCE_GRADE
        )
        retrieval_hits = sum(item in relevant for item in ranked)
        high_relevance_hits = sum(item in highly_relevant for item in ranked)
        rows.append({
            "case_id": case.case_id,
            "retrieval_recall_at_k": retrieval_hits / len(relevant),
            "retrieval_high_relevance_recall_at_k": (
                high_relevance_hits / len(highly_relevant) if highly_relevant else 0.0
            ),
            "retrieval_mrr_at_k": _reciprocal_rank(ranked, relevant),
            "retrieval_ndcg_at_k": _ndcg(ranked, case.relevance_judgments),
            "recommendation_hit_rate_at_3": float(any(item in relevant for item in top3)),
            "recommendation_precision_at_3": sum(item in relevant for item in top3) / 3.0,
            "recommendation_weighted_precision_at_3": sum(
                case.relevance_judgments.get(item, 0) for item in top3
            ) / (3.0 * MAX_RELEVANCE_GRADE),
            "recommendation_mrr_at_3": _reciprocal_rank(top3, relevant),
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
