from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.repositories.reindex_jobs import PokemonReindexJobRepository


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class _ClaimSession:
    def __init__(self, job):
        self.job = job
        self.statement = None
        self.flushes = 0

    def scalars(self, statement):
        self.statement = statement
        return _ScalarResult(self.job)

    def flush(self):
        self.flushes += 1


class _StateSession:
    def __init__(self, job):
        self.job = job

    def get(self, _model, job_id):
        return self.job if job_id == self.job.id else None


class ReindexJobRepositoryTests(unittest.TestCase):
    def job(self, status="queued"):
        return SimpleNamespace(
            id=uuid4(), pokemon_id=25, status=status,
            progress_current=0, progress_total=0, embedded=0, failed=0,
            message=None, last_error=None, queued_at=datetime.now(timezone.utc),
            started_at=None, finished_at=None, updated_at=datetime.now(timezone.utc),
        )

    def test_claim_uses_skip_locked_and_marks_job_running(self):
        job = self.job()
        session = _ClaimSession(job)
        claimed = PokemonReindexJobRepository(session).claim_next()
        sql = str(session.statement.compile(dialect=postgresql.dialect()))

        self.assertIs(claimed, job)
        self.assertIn("FOR UPDATE SKIP LOCKED", sql)
        self.assertEqual(job.status, "running")
        self.assertIsNotNone(job.started_at)
        self.assertEqual(session.flushes, 1)

    def test_progress_and_terminal_states_are_persisted(self):
        job = self.job("running")
        repository = PokemonReindexJobRepository(_StateSession(job))
        repository.progress(job.id, 2, 5, 2, 0, "working")
        self.assertEqual((job.progress_current, job.progress_total, job.message), (2, 5, "working"))

        repository.succeed(job.id, total=5, embedded=5, failed=0)
        self.assertEqual(job.status, "succeeded")
        self.assertEqual(job.progress_current, 5)
        self.assertIsNotNone(job.finished_at)

        failed = self.job("running")
        PokemonReindexJobRepository(_StateSession(failed)).fail(failed.id, "synthetic error")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.last_error, "synthetic error")


if __name__ == "__main__":
    unittest.main()
