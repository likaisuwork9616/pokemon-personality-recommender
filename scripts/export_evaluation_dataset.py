"""Export active, adjudicated evaluation cases to versioned JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import get_session_factory
from app.repositories.evaluation_admin import EvaluationAnnotationRepository


def write_jsonl(path: Path, cases: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination JSONL; existing files are atomically replaced.",
    )
    parser.add_argument("--dataset-version", help="Only export this active version.")
    args = parser.parse_args()

    with get_session_factory()() as session:
        cases = EvaluationAnnotationRepository(session).export_active_cases(
            args.dataset_version
        )
    if not cases:
        parser.error("no active, adjudicated cases matched the requested version")
    write_jsonl(args.output, cases)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "case_count": len(cases),
                "dataset_version": args.dataset_version,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
