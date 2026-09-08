"""Run the versioned offline recommendation evaluation set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import _default_engine_factory
from app.services.evaluation import EvaluationCase, evaluate_recommendations


def load_cases(path: Path) -> list[EvaluationCase]:
    cases = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        try:
            if "relevance" in payload:
                relevance = {
                    int(item["pokedex_number"]): int(item["grade"])
                    for item in payload["relevance"]
                }
                if len(relevance) != len(payload["relevance"]):
                    raise ValueError("duplicate Pokédex number")
            else:
                # Keep old binary datasets usable while versioned datasets move
                # to explicit graded judgments.
                relevance = {
                    int(value): 1
                    for value in payload["relevant_pokedex_numbers"]
                }
            cases.append(EvaluationCase(
                case_id=str(payload["id"]),
                query=str(payload["query"]),
                relevance_judgments=relevance,
            ))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid evaluation case at line {line_number}") from exc
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluation" / "recommendation_cases.jsonl")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--retrieval-k", type=int, default=10)
    parser.add_argument("--min-recall", type=float, default=0.0)
    parser.add_argument("--min-hit-rate", type=float, default=0.0)
    args = parser.parse_args()
    report = evaluate_recommendations(_default_engine_factory(), load_cases(args.dataset), retrieval_k=args.retrieval_k)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    metrics = report["metrics"]
    return int(metrics["retrieval_recall_at_k"] < args.min_recall or metrics["recommendation_hit_rate_at_3"] < args.min_hit_rate)


if __name__ == "__main__":
    raise SystemExit(main())
