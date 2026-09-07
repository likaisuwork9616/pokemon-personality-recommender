"""PostgreSQL-backed personality catalog and synonym matching."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from sqlalchemy import Text, bindparam, func, select
from sqlalchemy.orm import Session

from app.db.models import PersonalityTrait, PersonalityTraitSynonym, PersonalityVocabularyState
from app.personality_vocabulary import canonicalize_personality_text


PERSONALITY_DIMENSIONS = 16


@dataclass(frozen=True)
class PersonalityCatalog:
    trait_names: tuple[str, ...]
    synonyms_by_trait: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class PersonalityWeightedTerm:
    term: str
    weight: float


@dataclass(frozen=True)
class PublicPersonalityTrait:
    code: str
    name_zh: str
    weighted_terms: tuple[PersonalityWeightedTerm, ...]


@dataclass(frozen=True)
class PublicPersonalityCatalog:
    revision: int
    traits: tuple[PublicPersonalityTrait, ...]


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

    def revision(self) -> int:
        value = self.session.scalar(
            select(PersonalityVocabularyState.revision).where(PersonalityVocabularyState.id == 1)
        )
        if value is None:
            raise RuntimeError("personality vocabulary revision is missing")
        return int(value)

    def public_catalog(self) -> PublicPersonalityCatalog:
        """Return the active, weighted vocabulary intended for public display."""

        revision = (
            select(PersonalityVocabularyState.revision)
            .where(PersonalityVocabularyState.id == 1)
            .scalar_subquery()
        )
        rows = self.session.execute(
            select(
                revision.label("revision"),
                PersonalityTrait.code,
                PersonalityTrait.name_zh,
                PersonalityTrait.vector_index,
                PersonalityTraitSynonym.term,
                PersonalityTraitSynonym.language_code,
                PersonalityTraitSynonym.weight,
            )
            .join(
                PersonalityTraitSynonym,
                PersonalityTraitSynonym.trait_code == PersonalityTrait.code,
            )
            .where(
                PersonalityTrait.is_active.is_(True),
                PersonalityTraitSynonym.is_active.is_(True),
            )
            .order_by(PersonalityTrait.vector_index)
        ).all()

        if rows and rows[0].revision is None:
            raise RuntimeError("personality vocabulary revision is missing")

        grouped: dict[int, dict[str, object]] = {}
        revisions: set[int] = set()
        for row in rows:
            if row.revision is None:
                raise RuntimeError("personality vocabulary revision is missing")
            revisions.add(int(row.revision))
            vector_index = int(row.vector_index)
            entry = grouped.setdefault(
                vector_index,
                {
                    "code": str(row.code),
                    "name_zh": str(row.name_zh),
                    "terms": [],
                },
            )
            if entry["code"] != str(row.code) or entry["name_zh"] != str(row.name_zh):
                raise RuntimeError("personality vector index maps to multiple traits")
            terms = entry["terms"]
            assert isinstance(terms, list)
            terms.append(
                (
                    str(row.language_code),
                    str(row.term),
                    float(row.weight),
                )
            )

        expected_indexes = list(range(PERSONALITY_DIMENSIONS))
        if sorted(grouped) != expected_indexes:
            raise RuntimeError("active personality traits must define vector indexes 0-15")
        if len(revisions) != 1:
            raise RuntimeError("personality vocabulary revision is inconsistent")

        traits: list[PublicPersonalityTrait] = []
        for vector_index in expected_indexes:
            entry = grouped[vector_index]
            terms = entry["terms"]
            assert isinstance(terms, list)
            ordered_terms = sorted(
                terms,
                key=lambda item: (
                    0 if item[0].casefold().startswith("zh") else 1,
                    -item[2],
                    item[1],
                ),
            )
            traits.append(
                PublicPersonalityTrait(
                    code=str(entry["code"]),
                    name_zh=str(entry["name_zh"]),
                    weighted_terms=tuple(
                        PersonalityWeightedTerm(term=term, weight=weight)
                        for _language_code, term, weight in ordered_terms
                    ),
                )
            )

        return PublicPersonalityCatalog(
            revision=next(iter(revisions)),
            traits=tuple(traits),
        )

    def vector_for_text(self, text: str) -> tuple[float, ...]:
        """Return a normalized 16-dimensional vector from parameterized SQL."""

        query_text = canonicalize_personality_text(text)
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
                    query_parameter,
                    PersonalityTraitSynonym.normalized_term,
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
