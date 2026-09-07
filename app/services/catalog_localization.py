"""Traditional Chinese display names for structured Pokédex metadata.

The database keeps stable English identifiers for filtering, administration, and
future locales.  This module adds presentation names without changing those raw
values or depending on an external service at request time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal


TranslationGroup = Literal["ability", "egg_group", "growth_rate", "habitat"]
_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "catalog_zh_hant.json"
_SEPARATOR = re.compile(r"[|,]")
_GROUPS: tuple[TranslationGroup, ...] = (
    "ability",
    "egg_group",
    "growth_rate",
    "habitat",
)


@dataclass(frozen=True, slots=True)
class LocalizedTerm:
    code: str
    name_zh: str


@dataclass(frozen=True, slots=True)
class LocalizedAbilityTerm(LocalizedTerm):
    is_hidden: bool


def normalize_catalog_code(value: str) -> str:
    return value.strip().casefold().replace("_", "-")


@lru_cache(maxsize=1)
def _translations() -> dict[TranslationGroup, dict[str, str]]:
    payload = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    translations: dict[TranslationGroup, dict[str, str]] = {}
    for group in _GROUPS:
        entries = payload.get(group)
        if not isinstance(entries, dict) or not entries:
            raise RuntimeError(f"Catalog translation group is invalid: {group}")
        normalized: dict[str, str] = {}
        for code, name_zh in entries.items():
            if not isinstance(code, str) or not isinstance(name_zh, str):
                raise RuntimeError(f"Catalog translation entry is invalid: {group}")
            normalized_code = normalize_catalog_code(code)
            normalized_name = name_zh.strip()
            if not normalized_code or not normalized_name:
                raise RuntimeError(f"Catalog translation entry is blank: {group}")
            if normalized_code in normalized:
                raise RuntimeError(
                    f"Catalog translation code is duplicated: {group}/{normalized_code}"
                )
            normalized[normalized_code] = normalized_name
        translations[group] = normalized
    return translations


def split_catalog_codes(value: str | None) -> tuple[str, ...]:
    """Split legacy pipe/comma strings and de-duplicate identifiers in order."""

    if value is None:
        return ()
    codes: list[str] = []
    seen: set[str] = set()
    for item in _SEPARATOR.split(value):
        raw_code = item.strip()
        normalized_code = normalize_catalog_code(raw_code)
        if not normalized_code or normalized_code in seen:
            continue
        seen.add(normalized_code)
        codes.append(raw_code)
    return tuple(codes)


def has_catalog_translation(group: TranslationGroup, code: str) -> bool:
    return normalize_catalog_code(code) in _translations()[group]


def catalog_translation_count(group: TranslationGroup) -> int:
    return len(_translations()[group])


def localize_catalog_term(
    code: str | None,
    group: TranslationGroup,
) -> LocalizedTerm | None:
    if code is None or not code.strip():
        return None
    raw_code = code.strip()
    normalized_code = normalize_catalog_code(raw_code)
    name_zh = _translations()[group].get(normalized_code)
    if name_zh is None:
        return LocalizedTerm(code=raw_code, name_zh="未收錄")
    return LocalizedTerm(code=normalized_code, name_zh=name_zh)


def localize_catalog_terms(
    value: str | None,
    group: TranslationGroup,
) -> tuple[LocalizedTerm, ...]:
    return tuple(
        term
        for code in split_catalog_codes(value)
        if (term := localize_catalog_term(code, group)) is not None
    )


def localize_ability_terms(
    abilities: str | None,
    hidden_ability: str | None,
) -> tuple[LocalizedAbilityTerm, ...]:
    """Return every ability with an explicit hidden/regular classification."""

    hidden = localize_catalog_term(hidden_ability, "ability")
    hidden_code = normalize_catalog_code(hidden.code) if hidden is not None else None
    terms = list(localize_catalog_terms(abilities, "ability"))
    if hidden is not None and all(
        normalize_catalog_code(term.code) != hidden_code for term in terms
    ):
        terms.append(hidden)
    return tuple(
        LocalizedAbilityTerm(
            code=term.code,
            name_zh=term.name_zh,
            is_hidden=(
                hidden_code is not None
                and normalize_catalog_code(term.code) == hidden_code
            ),
        )
        for term in terms
    )
