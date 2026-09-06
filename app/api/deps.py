"""FastAPI dependencies shared by database-backed routers."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.repositories import PokemonRepository


def get_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def get_pokemon_repository(
    session: Annotated[Session, Depends(get_session)],
) -> PokemonRepository:
    return PokemonRepository(session)
