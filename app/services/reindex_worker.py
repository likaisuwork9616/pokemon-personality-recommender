"""One-job-at-a-time worker for the PostgreSQL reindex queue."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.repositories.reindex import PokemonReindexRepository
from app.repositories.reindex_jobs import PokemonReindexJobRepository
from app.repositories.vector import VectorRepository
from app.services.reindex import PokemonReindexService


class ReindexWorker:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def run_once(self) -> bool:
        with self.session_factory.begin() as claim_session:
            job = PokemonReindexJobRepository(claim_session).claim_next()
            if job is None:
                return False
            job_id, pokemon_id = job.id, job.pokemon_id

        try:
            with self.session_factory() as work_session:
                service = PokemonReindexService(
                    PokemonReindexRepository(work_session),
                    VectorRepository(work_session),
                )
                summary = service.rebuild(
                    pokemon_id,
                    progress_callback=self._progress_callback(job_id),
                )
                work_session.commit()
            with self.session_factory.begin() as finish_session:
                PokemonReindexJobRepository(finish_session).succeed(
                    job_id,
                    total=summary.discovered,
                    embedded=summary.embedded,
                    failed=summary.failed,
                )
        except Exception as exc:
            safe_error = f"{type(exc).__name__}: {exc}"[:2000]
            with self.session_factory.begin() as failure_session:
                PokemonReindexJobRepository(failure_session).fail(job_id, safe_error)
        return True

    def _progress_callback(self, job_id: UUID) -> Callable[[int, int, int, int, str], None]:
        def update(current: int, total: int, embedded: int, failed: int, message: str) -> None:
            with self.session_factory.begin() as progress_session:
                PokemonReindexJobRepository(progress_session).progress(
                    job_id, current, total, embedded, failed, message
                )

        return update
