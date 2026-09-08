"""Presentation-only paragraph formatting for public Pokédex entries."""

from __future__ import annotations

import re


DEFAULT_PARAGRAPH_MAX_CHARACTERS = 160
DEFAULT_PARAGRAPH_MAX_SENTENCES: int | None = None

_HARD_BREAK = re.compile(r"\r\n|\r|\n")
_SENTENCE_ENDINGS = frozenset("。")
_REPEATED_ENDINGS = frozenset("。！？!?；;.")
_CLOSING_PUNCTUATION = frozenset("」』）)】]》〉”’\"")
_WEAK_BREAKS = frozenset("！？!?；;，,、：:")


def _display_length(value: str) -> int:
    return sum(1 for character in value if not character.isspace())


def _is_sentence_ending(value: str, index: int) -> bool:
    character = value[index]
    if character in _SENTENCE_ENDINGS:
        return True
    if character in "！？!?":
        following = value[index + 1] if index + 1 < len(value) else ""
        return not following or following.isspace()
    if character != ".":
        return False

    previous = value[index - 1] if index > 0 else ""
    following = value[index + 1] if index + 1 < len(value) else ""
    if previous.isdigit() and following.isdigit():
        return False
    if previous == "." or following == ".":
        return False
    return True


def _sentences(value: str) -> tuple[str, ...]:
    sentences: list[str] = []
    start = 0
    index = 0
    while index < len(value):
        if not _is_sentence_ending(value, index):
            index += 1
            continue

        end = index + 1
        while end < len(value) and value[end] in _REPEATED_ENDINGS:
            end += 1
        while end < len(value) and value[end] in _CLOSING_PUNCTUATION:
            end += 1
        while end < len(value) and value[end].isspace():
            end += 1

        sentence = value[start:end]
        if sentence.strip():
            sentences.append(sentence)
        start = end
        index = end

    remainder = value[start:]
    if remainder.strip():
        sentences.append(remainder)
    return tuple(sentences)


def _split_oversized_fragment(
    value: str,
    *,
    max_characters: int,
) -> tuple[str, ...]:
    """Bound a long fragment, preferring natural clause breaks over hard cuts."""

    pieces: list[str] = []
    remaining = value
    preferred_floor = max(1, max_characters // 2)

    while _display_length(remaining) > max_characters:
        visible_characters = 0
        hard_cut = len(remaining)
        weak_cut: int | None = None

        for index, character in enumerate(remaining):
            if not character.isspace():
                visible_characters += 1
            if (
                character in _WEAK_BREAKS
                and visible_characters >= preferred_floor
                and visible_characters <= max_characters
            ):
                weak_cut = index + 1
            if visible_characters >= max_characters:
                hard_cut = index + 1
                break

        cut = weak_cut or hard_cut
        while cut < len(remaining) and remaining[cut].isspace():
            cut += 1
        pieces.append(remaining[:cut])
        remaining = remaining[cut:]

    if remaining:
        pieces.append(remaining)
    return tuple(pieces)


def split_description_paragraphs(
    value: str,
    *,
    max_characters: int = DEFAULT_PARAGRAPH_MAX_CHARACTERS,
    max_sentences: int | None = DEFAULT_PARAGRAPH_MAX_SENTENCES,
) -> tuple[str, ...]:
    """Create readable display paragraphs without changing stored descriptions.

    Source line breaks are hard paragraph boundaries. Within each source block,
    complete sentences are grouped to the character limit. Exceptionally long
    sentences prefer a comma-like clause boundary and otherwise use a hard-wrap
    fallback, so every rendered paragraph remains readable.
    """

    if max_characters < 1:
        raise ValueError("max_characters must be positive")
    if max_sentences is not None and max_sentences < 1:
        raise ValueError("max_sentences must be positive")

    paragraphs: list[str] = []
    for raw_block in _HARD_BREAK.split(value):
        block = raw_block.strip()
        if not block:
            continue

        current: list[str] = []
        current_length = 0
        for sentence in _sentences(block):
            for fragment in _split_oversized_fragment(
                sentence,
                max_characters=max_characters,
            ):
                fragment_length = _display_length(fragment)
                if current and (
                    (
                        max_sentences is not None
                        and len(current) >= max_sentences
                    )
                    or current_length + fragment_length > max_characters
                ):
                    paragraphs.append("".join(current).strip())
                    current = []
                    current_length = 0
                current.append(fragment)
                current_length += fragment_length

        if current:
            paragraphs.append("".join(current).strip())

    return tuple(paragraphs)
