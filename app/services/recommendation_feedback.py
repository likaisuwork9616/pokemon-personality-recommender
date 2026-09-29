"""Transaction boundary for privacy-safe recommendation feedback."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from app.repositories.recommendation_feedback import RecommendationFeedbackRepository


class RecommendationFeedbackService:
    def __init__(
        self,
        session_factory: Callable[[], Any],
        repository_factory: Callable[[Any], RecommendationFeedbackRepository] = RecommendationFeedbackRepository,
    ) -> None:
        self.session_factory = session_factory
        self.repository_factory = repository_factory

    def record_impression(
        self,
        *,
        algorithm_version: str,
        ranked_pokemon: list[tuple[int, int]],
    ) -> UUID:
        if [rank for rank, _pokemon_id in ranked_pokemon] != [1, 2, 3]:
            raise ValueError("feedback receipt requires ranks 1, 2 and 3")
        pokemon_ids = [pokemon_id for _rank, pokemon_id in ranked_pokemon]
        if len(set(pokemon_ids)) != 3 or any(value <= 0 for value in pokemon_ids):
            raise ValueError("feedback receipt requires three unique Pokémon")
        recommendation_id = uuid4()
        with self.session_factory() as session:
            self.repository_factory(session).create_impression(
                recommendation_id=recommendation_id,
                algorithm_version=algorithm_version,
                ranked_pokemon=ranked_pokemon,
            )
            session.commit()
        return recommendation_id

    def submit_feedback(
        self,
        *,
        recommendation_id: UUID,
        pokemon_id: int,
        rank: int,
        verdict: str,
        reason: str,
    ) -> bool:
        with self.session_factory() as session:
            created = self.repository_factory(session).upsert_feedback(
                recommendation_id=recommendation_id,
                pokemon_id=pokemon_id,
                rank=rank,
                verdict=verdict,
                reason=reason,
            )
            session.commit()
        return created

    def summary(self) -> dict[str, object]:
        with self.session_factory() as session:
            return self.repository_factory(session).summary()
