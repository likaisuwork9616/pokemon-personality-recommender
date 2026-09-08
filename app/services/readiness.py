"""Bounded live database readiness checks without error-detail exposure."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable, Mapping

from sqlalchemy import text


@dataclass(frozen=True)
class ReadinessConfig:
    database_timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        if not 0.05 <= self.database_timeout_seconds <= 10.0:
            raise ValueError("READINESS_DB_TIMEOUT_SECONDS must be between 0.05 and 10")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ReadinessConfig":
        values = env if env is not None else os.environ
        try:
            timeout = float(values.get("READINESS_DB_TIMEOUT_SECONDS", "2"))
        except ValueError as exc:
            raise ValueError("READINESS_DB_TIMEOUT_SECONDS must be numeric") from exc
        return cls(database_timeout_seconds=timeout)


class DatabaseReadinessProbe:
    """Open a fresh session scope and execute a real database round-trip."""

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self._session_factory = session_factory

    def check(self) -> bool:
        try:
            with self._session_factory() as session:
                return session.execute(text("SELECT 1")).scalar_one() == 1
        except Exception:
            return False
