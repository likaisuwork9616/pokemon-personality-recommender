"""Administrator writes for the PostgreSQL personality vocabulary."""

from __future__ import annotations

import unicodedata
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import PersonalityTrait, PersonalityTraitSynonym, PersonalityVocabularyState
from app.repositories.personality import PersonalityCatalog, PersonalityRepository


class AdminPersonalityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_traits(self) -> list[PersonalityTrait]:
        return list(self.session.scalars(
            select(PersonalityTrait)
            .options(selectinload(PersonalityTrait.synonyms))
            .order_by(PersonalityTrait.vector_index)
        ))

    def catalog(self) -> PersonalityCatalog:
        return PersonalityRepository(self.session).catalog()

    def revision(self) -> int:
        return PersonalityRepository(self.session).revision()

    @staticmethod
    def normalize_term(term: str) -> tuple[str, str]:
        display = unicodedata.normalize("NFKC", term).strip()
        return display, display.casefold()

    def bump_revision(self) -> int:
        state = self.session.scalar(
            select(PersonalityVocabularyState)
            .where(PersonalityVocabularyState.id == 1)
            .with_for_update()
        )
        if state is None:
            raise RuntimeError("personality vocabulary revision is missing")
        state.revision += 1
        return int(state.revision)

    def get_trait(self, code: str) -> PersonalityTrait | None:
        return self.session.scalar(
            select(PersonalityTrait)
            .options(selectinload(PersonalityTrait.synonyms))
            .where(PersonalityTrait.code == code)
        )

    def rename_trait(self, trait: PersonalityTrait, name_zh: str) -> PersonalityTrait:
        trait.name_zh = name_zh.strip()
        return trait

    def add_synonym(self, trait: PersonalityTrait, *, term: str, language_code: str, weight: float, is_active: bool) -> PersonalityTraitSynonym:
        display_term, normalized_term = self.normalize_term(term)
        item = PersonalityTraitSynonym(
            trait_code=trait.code,
            term=display_term,
            normalized_term=normalized_term,
            language_code=language_code.strip(),
            weight=weight,
            is_active=is_active,
        )
        self.session.add(item)
        return item

    def get_synonym(self, trait_code: str, term: str) -> PersonalityTraitSynonym | None:
        return self.session.get(PersonalityTraitSynonym, (trait_code, term))

    def update_synonym(self, item: PersonalityTraitSynonym, *, term: str | None = None, language_code: str | None = None, weight: float | None = None, is_active: bool | None = None) -> PersonalityTraitSynonym:
        if term is not None:
            item.term, item.normalized_term = self.normalize_term(term)
        if language_code is not None:
            item.language_code = language_code.strip()
        if weight is not None:
            item.weight = weight
        if is_active is not None:
            if not is_active and item.is_active:
                self.session.execute(
                    select(PersonalityTrait.code)
                    .where(PersonalityTrait.code == item.trait_code)
                    .with_for_update()
                )
                if self.active_synonym_count(item.trait_code) <= 1:
                    raise ValueError("啟用中的人格特質至少需要一個啟用同義詞。")
            item.is_active = is_active
        return item

    def active_synonym_count(self, trait_code: str) -> int:
        return int(self.session.scalar(
            select(func.count()).select_from(PersonalityTraitSynonym).where(
                PersonalityTraitSynonym.trait_code == trait_code,
                PersonalityTraitSynonym.is_active.is_(True),
            )
        ) or 0)
