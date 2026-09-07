"""PostgreSQL-backed personality catalog and synonym matching."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from sqlalchemy import Text, bindparam, func, select
from sqlalchemy.orm import Session

from app.db.models import PersonalityTrait, PersonalityTraitSynonym


PERSONALITY_DIMENSIONS = 16


@dataclass(frozen=True)
class PersonalityCatalog:
    trait_names: tuple[str, ...]
    synonyms_by_trait: dict[str, tuple[str, ...]]


class PersonalityRepository:
    """Keep the vocabulary in PostgreSQL and perform request matching in SQL."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def catalog(self) -> PersonalityCatalog:
        trait_rows = self.session.execute(
            select(
                PersonalityTrait.code,
                PersonalityTrait.name_zh,
                PersonalityTrait.vector_index,
            )
            .where(PersonalityTrait.is_active.is_(True))
            .order_by(PersonalityTrait.vector_index)
        ).all()
        expected_indexes = list(range(PERSONALITY_DIMENSIONS))
        actual_indexes = [int(row.vector_index) for row in trait_rows]
        if actual_indexes != expected_indexes:
            raise RuntimeError("active personality traits must define vector indexes 0-15")

        synonym_rows = self.session.execute(
            select(
                PersonalityTraitSynonym.trait_code,
                PersonalityTraitSynonym.term,
            )
            .join(
                PersonalityTrait,
                PersonalityTrait.code == PersonalityTraitSynonym.trait_code,
            )
            .where(
                PersonalityTrait.is_active.is_(True),
                PersonalityTraitSynonym.is_active.is_(True),
            )
            .order_by(
                PersonalityTrait.vector_index,
                PersonalityTraitSynonym.term,
            )
        ).all()
        synonyms_by_code: dict[str, list[str]] = {
            str(row.code): [] for row in trait_rows
        }
        for row in synonym_rows:
            synonyms_by_code[str(row.trait_code)].append(str(row.term))
        if any(not terms for terms in synonyms_by_code.values()):
            raise RuntimeError("every active personality trait requires a synonym")

        return PersonalityCatalog(
            trait_names=tuple(str(row.name_zh) for row in trait_rows),
            synonyms_by_trait={
                str(row.name_zh): tuple(synonyms_by_code[str(row.code)])
                for row in trait_rows
            },
        )

    def vector_for_text(self, text: str) -> tuple[float, ...]:
        """Return a normalized 16-dimensional vector from parameterized SQL."""

        query_text = str(text).strip()
        if not query_text:
            raise ValueError("personality query must not be blank")
        query_parameter = bindparam("personality_query", type_=Text())
        statement = (
            select(
                PersonalityTrait.vector_index,
                func.sum(PersonalityTraitSynonym.weight).label("score"),
            )
            .join(
                PersonalityTraitSynonym,
                PersonalityTraitSynonym.trait_code == PersonalityTrait.code,
            )
            .where(
                PersonalityTrait.is_active.is_(True),
                PersonalityTraitSynonym.is_active.is_(True),
                func.strpos(
                    func.lower(query_parameter),
                    func.lower(PersonalityTraitSynonym.term),
                )
                > 0,
            )
            .group_by(PersonalityTrait.vector_index)
            .order_by(PersonalityTrait.vector_index)
        )
        rows = self.session.execute(
            statement,
            {"personality_query": query_text},
        ).all()

        vector = [0.0] * PERSONALITY_DIMENSIONS
        for row in rows:
            vector_index = int(row.vector_index)
            if not 0 <= vector_index < PERSONALITY_DIMENSIONS:
                raise RuntimeError("personality vector index is outside 0-15")
            vector[vector_index] = float(row.score)
        norm = sqrt(sum(value * value for value in vector))
        if norm == 0:
            return tuple(vector)
        return tuple(value / norm for value in vector)
