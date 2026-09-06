"""Incrementally build current Pokémon knowledge-chunk embeddings."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import get_session_factory
from app.repositories import VectorRepository
from app.services.embedding import (
    DEFAULT_MODEL_NAME,
    EmbeddingConfig,
    EmbeddingService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build only missing, stale, failed, or hash-mismatched vectors."
    )
    parser.add_argument(
        "--model",
        default=os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL_NAME),
    )
    parser.add_argument(
        "--model-version",
        default=os.getenv("EMBEDDING_MODEL_VERSION", "default"),
    )
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument(
        "--database-url",
        help="Override DATABASE_URL for this command.",
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

    config = EmbeddingConfig(
        model_name=args.model,
        model_version=args.model_version,
        batch_size=args.batch_size,
    )
    with session_factory.begin() as session:
        summary = EmbeddingService(
            VectorRepository(session),
            config=config,
        ).rebuild()

    print(json.dumps(asdict(summary), ensure_ascii=False, sort_keys=True))
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
