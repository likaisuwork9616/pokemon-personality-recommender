"""Import the canonical Pokemon CSV into PostgreSQL."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import get_session_factory
from app.services.csv_importer import (
    DEFAULT_CSV_PATH,
    CsvPokemonImporter,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Idempotently import the Pokemon CSV into PostgreSQL."
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and execute the import transaction, then roll it back.",
    )
    parser.add_argument(
        "--database-url",
        help="Override DATABASE_URL for this command without changing the environment.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.database_url:
        engine = create_engine(args.database_url, pool_pre_ping=True)
        session_factory = sessionmaker(
            bind=engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )
    else:
        session_factory = get_session_factory()

    summary = CsvPokemonImporter(session_factory).import_file(
        args.csv,
        dry_run=args.dry_run,
    )
    print(json.dumps(asdict(summary), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
