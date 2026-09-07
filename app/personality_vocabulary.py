"""Canonical text handling for the PostgreSQL personality vocabulary."""

from __future__ import annotations

import unicodedata


FORBIDDEN_VOCABULARY_CATEGORIES = frozenset({"Cc", "Cf"})


def canonicalize_personality_text(value: str) -> str:
    """Return the NFKC/casefold form used by both stored terms and queries.

    Leading and trailing whitespace is removed. Runs of allowed Unicode
    whitespace are represented by one ASCII space so an administrator-entered
    phrase and an equivalent user query share one deterministic form.
    """

    normalized = unicodedata.normalize("NFKC", str(value))
    return " ".join(normalized.split()).casefold()


def normalize_vocabulary_value(
    value: str,
    *,
    max_length: int,
    label: str,
) -> tuple[str, str]:
    """Validate and return display/canonical forms for an editable term.

    C0/C1 controls and Unicode format characters are rejected rather than
    silently removed. Ordinary Unicode spacing is allowed, then trimmed and
    collapsed by :func:`canonicalize_personality_text` semantics.
    """

    source = str(value)
    normalized = unicodedata.normalize("NFKC", source)
    if any(
        unicodedata.category(character) in FORBIDDEN_VOCABULARY_CATEGORIES
        for character in (*source, *normalized)
    ):
        raise ValueError(f"{label}不可包含控制或格式字元。")

    display = " ".join(normalized.split())
    canonical = canonicalize_personality_text(display)
    if not canonical:
        raise ValueError(f"{label}不可為空白。")
    if len(display) > max_length or len(canonical) > max_length:
        raise ValueError(f"{label}正規化後不可超過 {max_length} 個字元。")
    return display, canonical
