"""Measure pgvector exact versus HNSW latency and recall on stored vectors."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from statistics import mean
import sys
from time import perf_counter
from typing import Sequence

from sqlalchemy import Connection, create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.session import get_database_url


HNSW_INDEX_NAME = "ix_chunk_embeddings_embedding_hnsw"


@dataclass(frozen=True)
class LatencySummary:
    samples: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    queries_per_second: float


def percentile(values: Sequence[float], percentile_value: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * percentile_value / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize_latencies(values: Sequence[float]) -> LatencySummary:
    if not values:
        raise ValueError("latency summary requires at least one sample")
    average = mean(values)
    return LatencySummary(
        samples=len(values),
        mean_ms=round(average, 4),
        p50_ms=round(percentile(values, 50), 4),
        p95_ms=round(percentile(values, 95), 4),
        min_ms=round(min(values), 4),
        max_ms=round(max(values), 4),
        queries_per_second=round(1000.0 / average, 2) if average else 0.0,
    )


def recall_at_k(expected: Sequence[str], actual: Sequence[str]) -> float:
    if not expected:
        raise ValueError("expected result cannot be empty")
    return len(set(expected).intersection(actual)) / len(set(expected))


def _set_config(connection: Connection, name: str, value: str) -> None:
    connection.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": name, "value": value},
    )


def _configure_mode(
    connection: Connection,
    *,
    mode: str,
    ef_search: int,
    iterative_scan: str,
) -> None:
    if mode == "exact":
        _set_config(connection, "enable_indexscan", "off")
        _set_config(connection, "enable_bitmapscan", "off")
        _set_config(connection, "enable_seqscan", "on")
        return
    if mode != "hnsw":
        raise ValueError("mode must be exact or hnsw")
    _set_config(connection, "enable_indexscan", "on")
    _set_config(connection, "enable_bitmapscan", "on")
    _set_config(connection, "enable_seqscan", "off")
    _set_config(connection, "hnsw.ef_search", str(ef_search))
    _set_config(connection, "hnsw.iterative_scan", iterative_scan)


SEARCH_SQL = text(
    """
    SELECT chunk_id::text
    FROM pokemon_chunk_embeddings
    WHERE embedding_model_id = :model_id
      AND status = 'ready'
      AND embedding IS NOT NULL
    ORDER BY embedding <=> CAST(:query_vector AS vector)
    LIMIT :top_k
    """
)


def _search(
    connection: Connection,
    *,
    model_id: int,
    query_vector: str,
    top_k: int,
) -> list[str]:
    return [
        str(value)
        for value in connection.scalars(
            SEARCH_SQL,
            {"model_id": model_id, "query_vector": query_vector, "top_k": top_k},
        )
    ]


def _measure_mode(
    connection: Connection,
    *,
    mode: str,
    vectors: Sequence[str],
    model_id: int,
    top_k: int,
    warmup: int,
    ef_search: int,
    iterative_scan: str,
) -> tuple[list[float], list[list[str]]]:
    _configure_mode(
        connection,
        mode=mode,
        ef_search=ef_search,
        iterative_scan=iterative_scan,
    )
    for vector in vectors[:warmup]:
        _search(connection, model_id=model_id, query_vector=vector, top_k=top_k)

    latencies: list[float] = []
    results: list[list[str]] = []
    for vector in vectors:
        started = perf_counter()
        hits = _search(
            connection,
            model_id=model_id,
            query_vector=vector,
            top_k=top_k,
        )
        latencies.append((perf_counter() - started) * 1000.0)
        results.append(hits)
    return latencies, results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark exact and HNSW search latency plus recall@k."
    )
    parser.add_argument("--database-url", default=get_database_url())
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--ef-search", type=int, default=100)
    parser.add_argument(
        "--iterative-scan",
        choices=("strict_order", "relaxed_order"),
        default="strict_order",
    )
    parser.add_argument(
        "--minimum-corpus-size",
        type=int,
        default=0,
        help="Fail when the active vector corpus is smaller than this value.",
    )
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.sample_size <= 1000:
        raise SystemExit("--sample-size must be between 1 and 1000")
    if not 1 <= args.top_k <= 200:
        raise SystemExit("--top-k must be between 1 and 200")
    if not 0 <= args.warmup <= args.sample_size:
        raise SystemExit("--warmup must be between 0 and sample-size")
    if not 1 <= args.ef_search <= 1000:
        raise SystemExit("--ef-search must be between 1 and 1000")

    engine = create_engine(args.database_url, pool_pre_ping=True)
    with engine.connect() as connection, connection.begin():
        index_definition = connection.scalar(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' AND indexname = :index_name"
            ),
            {"index_name": HNSW_INDEX_NAME},
        )
        if not index_definition or "USING hnsw" not in str(index_definition):
            raise SystemExit(
                f"missing HNSW index {HNSW_INDEX_NAME}; run alembic upgrade head"
            )

        model_id = connection.scalar(
            text(
                "SELECT id FROM embedding_models WHERE is_active IS TRUE "
                "ORDER BY id LIMIT 1"
            )
        )
        if model_id is None:
            raise SystemExit("no active embedding model")
        corpus_size = int(
            connection.scalar(
                text(
                    "SELECT count(*) FROM pokemon_chunk_embeddings "
                    "WHERE embedding_model_id = :model_id "
                    "AND status = 'ready' AND embedding IS NOT NULL"
                ),
                {"model_id": model_id},
            )
            or 0
        )
        if corpus_size < args.minimum_corpus_size:
            raise SystemExit(
                f"corpus has {corpus_size} vectors; minimum is "
                f"{args.minimum_corpus_size}"
            )
        vectors = list(
            connection.scalars(
                text(
                    "SELECT embedding::text FROM pokemon_chunk_embeddings "
                    "WHERE embedding_model_id = :model_id "
                    "AND status = 'ready' AND embedding IS NOT NULL "
                    "ORDER BY md5(chunk_id::text) LIMIT :sample_size"
                ),
                {"model_id": model_id, "sample_size": args.sample_size},
            )
        )
        if len(vectors) < args.sample_size:
            raise SystemExit(
                f"requested {args.sample_size} samples but only {len(vectors)} exist"
            )

        exact_latency, exact_results = _measure_mode(
            connection,
            mode="exact",
            vectors=vectors,
            model_id=int(model_id),
            top_k=args.top_k,
            warmup=args.warmup,
            ef_search=args.ef_search,
            iterative_scan=args.iterative_scan,
        )
        hnsw_latency, hnsw_results = _measure_mode(
            connection,
            mode="hnsw",
            vectors=vectors,
            model_id=int(model_id),
            top_k=args.top_k,
            warmup=args.warmup,
            ef_search=args.ef_search,
            iterative_scan=args.iterative_scan,
        )

    recalls = [
        recall_at_k(expected, actual)
        for expected, actual in zip(exact_results, hnsw_results, strict=True)
    ]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus_size": corpus_size,
        "sample_size": args.sample_size,
        "top_k": args.top_k,
        "index": {
            "name": HNSW_INDEX_NAME,
            "m": 16,
            "ef_construction": 64,
            "ef_search": args.ef_search,
            "iterative_scan": args.iterative_scan,
        },
        "exact": asdict(summarize_latencies(exact_latency)),
        "hnsw": asdict(summarize_latencies(hnsw_latency)),
        "recall_at_k": {
            "mean": round(mean(recalls), 6),
            "minimum": round(min(recalls), 6),
        },
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
