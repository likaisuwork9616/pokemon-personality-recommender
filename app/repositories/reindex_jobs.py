"""Durable queue operations for background Pokémon reindexing."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Pokemon, PokemonReindexJob


ACTIVE_STATUSES = ("queued", "running")


class PokemonReindexJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(self, pokemon_id: int) -> tuple[PokemonReindexJob, bool]:
        if self.session.get(Pokemon, pokemon_id) is None:
            raise LookupError(pokemon_id)
        existing = self.session.scalars(
            select(PokemonReindexJob)
            .where(PokemonReindexJob.pokemon_id == pokemon_id, PokemonReindexJob.status.in_(ACTIVE_STATUSES))
            .order_by(PokemonReindexJob.queued_at.desc())
            .limit(1)
        ).first()
        if existing is not None:
            return existing, False
        job = PokemonReindexJob(id=uuid4(), pokemon_id=pokemon_id, status="queued", message="等待 worker 處理")
        self.session.add(job)
        self.session.flush()
        return job, True

    def get(self, job_id: UUID) -> PokemonReindexJob | None:
        return self.session.get(PokemonReindexJob, job_id)

    def claim_next(self) -> PokemonReindexJob | None:
        job = self.session.scalars(
            select(PokemonReindexJob)
            .where(PokemonReindexJob.status == "queued")
            .order_by(PokemonReindexJob.queued_at, PokemonReindexJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).first()
        if job is None:
            return None
        now = datetime.now(timezone.utc)
        job.status = "running"
        job.started_at = now
        job.updated_at = now
        job.message = "正在準備知識文件"
        self.session.flush()
        return job

    def progress(self, job_id: UUID, current: int, total: int, embedded: int, failed: int, message: str) -> None:
        job = self.get(job_id)
        if job is None or job.status != "running":
            return
        job.progress_current = current
        job.progress_total = total
        job.embedded = embedded
        job.failed = failed
        job.message = message[:500]
        job.updated_at = datetime.now(timezone.utc)

    def succeed(self, job_id: UUID, *, total: int, embedded: int, failed: int) -> None:
        job = self.get(job_id)
        if job is None:
            return
        now = datetime.now(timezone.utc)
        job.status = "succeeded" if failed == 0 else "failed"
        job.progress_current = total
        job.progress_total = total
        job.embedded = embedded
        job.failed = failed
        job.message = "索引重建完成" if failed == 0 else "部分 chunks 建立失敗，可重新排程"
        job.finished_at = now
        job.updated_at = now

    def fail(self, job_id: UUID, error: str) -> None:
        job = self.get(job_id)
        if job is None:
            return
        now = datetime.now(timezone.utc)
        job.status = "failed"
        job.message = "索引重建失敗，可重新排程"
        job.last_error = error[:2000]
        job.finished_at = now
        job.updated_at = now
