"""Delete anonymous recommendation receipts older than the retention window."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import get_session_factory
from app.repositories.recommendation_feedback import RecommendationFeedbackRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retention-days",
        type=int,
        default=90,
        help="Keep this many complete UTC days (default: 90).",
    )
    args = parser.parse_args()
    if not 7 <= args.retention_days <= 365:
        parser.error("--retention-days must be between 7 and 365")

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.retention_days)
    with get_session_factory()() as session:
        deleted = RecommendationFeedbackRepository(session).purge_before(cutoff)
        session.commit()
    print(
        json.dumps(
            {
                "retention_days": args.retention_days,
                "cutoff": cutoff.isoformat(),
                "deleted_impressions": deleted,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
