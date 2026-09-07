"""Run the durable Pokémon reindex worker."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import get_session_factory
from app.services.reindex_worker import ReindexWorker


def main() -> int:
    interval = max(0.1, float(os.getenv("REINDEX_WORKER_POLL_SECONDS", "2")))
    stopping = False

    def stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    worker = ReindexWorker(get_session_factory())
    print("reindex worker ready", flush=True)
    while not stopping:
        if not worker.run_once():
            time.sleep(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
