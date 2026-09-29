"""Agreement and coverage metrics for collaborative relevance annotation."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from statistics import mean
from typing import Iterable
from uuid import UUID


@dataclass(frozen=True)
class AnnotationQualityRow:
    case_id: UUID
    segment: str
    query_length: int
    pokemon_id: int
    annotator: str | None = None
    grade: int | None = None
    final_grade: int | None = None


def query_length_bucket(length: int) -> str:
    if length < 40:
        return "short"
    if length < 80:
        return "medium"
    return "long"


def quadratic_weighted_kappa(left: list[int], right: list[int]) -> float | None:
    """Return quadratic weighted Cohen's kappa for aligned 0–3 labels."""

    if len(left) != len(right) or not left:
        return None
    levels = range(4)
    denominator = 9.0
    observed = mean(((a - b) ** 2) / denominator for a, b in zip(left, right))
    left_counts = Counter(left)
    right_counts = Counter(right)
    size = float(len(left))
    expected = sum(
        (((a - b) ** 2) / denominator)
        * (left_counts[a] / size)
        * (right_counts[b] / size)
        for a in levels
        for b in levels
    )
    if expected == 0:
        return 1.0 if observed == 0 else 0.0
    return 1.0 - (observed / expected)


def _slice_report(rows: list[AnnotationQualityRow]) -> dict[str, float | int]:
    items = {(row.case_id, row.pokemon_id) for row in rows}
    annotations: dict[tuple[UUID, int], set[str]] = defaultdict(set)
    conflicts: dict[tuple[UUID, int], set[int]] = defaultdict(set)
    adjudicated = set()
    for row in rows:
        key = (row.case_id, row.pokemon_id)
        if row.annotator is not None and row.grade is not None:
            annotations[key].add(row.annotator)
            conflicts[key].add(row.grade)
        if row.final_grade is not None:
            adjudicated.add(key)
    total = len(items)
    double_labeled = sum(len(annotations[key]) >= 2 for key in items)
    conflict_count = sum(
        len(annotations[key]) >= 2 and len(conflicts[key]) > 1 for key in items
    )
    return {
        "case_count": len({row.case_id for row in rows}),
        "candidate_count": total,
        "double_annotation_coverage": round(double_labeled / total, 6) if total else 0.0,
        "conflict_rate": round(conflict_count / double_labeled, 6) if double_labeled else 0.0,
        "adjudication_coverage": round(len(adjudicated) / total, 6) if total else 0.0,
    }


def build_annotation_quality_report(
    source_rows: Iterable[AnnotationQualityRow],
) -> dict[str, object]:
    """Build overall, annotator-pair, segment and query-length reports."""

    rows = list(source_rows)
    labels: dict[tuple[UUID, int], dict[str, int]] = defaultdict(dict)
    for row in rows:
        if row.annotator is not None and row.grade is not None:
            labels[(row.case_id, row.pokemon_id)][row.annotator] = row.grade

    annotators = sorted({name for judgments in labels.values() for name in judgments})
    pairs = []
    for left_name, right_name in combinations(annotators, 2):
        common = [
            judgments
            for judgments in labels.values()
            if left_name in judgments and right_name in judgments
        ]
        if not common:
            continue
        score = quadratic_weighted_kappa(
            [judgment[left_name] for judgment in common],
            [judgment[right_name] for judgment in common],
        )
        pairs.append(
            {
                "annotator_a": left_name,
                "annotator_b": right_name,
                "common_judgment_count": len(common),
                "quadratic_weighted_kappa": round(score, 6) if score is not None else None,
            }
        )

    overall = _slice_report(rows)
    overall.update(
        {
            "annotator_count": len(annotators),
            "pair_count": len(pairs),
            "mean_quadratic_weighted_kappa": (
                round(
                    mean(
                        pair["quadratic_weighted_kappa"]
                        for pair in pairs
                        if pair["quadratic_weighted_kappa"] is not None
                    ),
                    6,
                )
                if any(pair["quadratic_weighted_kappa"] is not None for pair in pairs)
                else None
            ),
        }
    )

    segments = {
        name: _slice_report([row for row in rows if row.segment == name])
        for name in sorted({row.segment for row in rows})
    }
    lengths = {
        bucket: _slice_report(
            [row for row in rows if query_length_bucket(row.query_length) == bucket]
        )
        for bucket in ("short", "medium", "long")
    }
    return {
        "overall": overall,
        "annotator_pairs": pairs,
        "slices": {"segment": segments, "query_length": lengths},
    }
