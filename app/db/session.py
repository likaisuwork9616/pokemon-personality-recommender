"""Lazy SQLAlchemy engine and session-factory construction."""

from functools import lru_cache
import os
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://pokemon:pokemon@localhost:5432/pokemon"
)


def get_database_url() -> str:
    """Return the configured PostgreSQL URL without opening a connection."""

    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create one process-local, pre-ping-enabled SQLAlchemy engine."""

    return create_engine(get_database_url(), pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the process-local session factory."""

    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def session_scope() -> Iterator[Session]:
    """Yield a session and guarantee that it is closed by the caller loop."""

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
