"""Shared, local MBTI reference affinities; never a personality diagnosis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from app.personality_vocabulary import canonicalize_personality_text


EMBEDDING_DIMENSIONS = 384
MBTI_DIMENSIONS = 16


def normalized_embedding(value: Sequence[float] | np.ndarray) -> np.ndarray:
    vector = np.asarray(value, dtype=float)
    if vector.shape != (EMBEDDING_DIMENSIONS,) or not np.isfinite(vector).all():
        raise ValueError("expected a finite 384-dimensional embedding")
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else vector.copy()


def cosine_affinity(first: Sequence[float], second: Sequence[float]) -> float:
    left, right = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    if left.shape != (MBTI_DIMENSIONS,) or right.shape != left.shape:
        raise ValueError("expected two 16-dimensional affinity vectors")
    if not np.isfinite(left).all() or not np.isfinite(right).all():
        raise ValueError("affinity vectors must be finite")
    norm = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.clip(np.dot(left, right) / norm, 0, 1)) if norm > 0 else 0.0


@dataclass(frozen=True)
class MbtiScorer:
    """An immutable catalog/prototype pair shared by both sides of a match."""

    catalog: Any
    prototype_vectors: np.ndarray

    def __post_init__(self) -> None:
        if len(self.catalog.profiles) != MBTI_DIMENSIONS:
            raise ValueError("MBTI catalog must contain 16 profiles")
        prototypes = np.asarray(self.prototype_vectors, dtype=float)
        if prototypes.shape != (MBTI_DIMENSIONS, EMBEDDING_DIMENSIONS):
            raise ValueError("expected 16 prototype embeddings")
        prototypes = np.stack([normalized_embedding(row) for row in prototypes])
        prototypes.setflags(write=False)
        object.__setattr__(self, "prototype_vectors", prototypes)

    @classmethod
    def from_encoder(cls, catalog: Any, encoder: Any) -> MbtiScorer:
        # Short character windows ensure later preferences/strengths contribute
        # even with multilingual encoders that truncate long input sequences.
        windows: list[str] = []
        spans: list[tuple[int, int]] = []
        for profile in catalog.profiles:
            text = profile.matching_text
            start = len(windows)
            windows.extend(text[offset:offset + 64] for offset in range(0, len(text), 64))
            spans.append((start, len(windows)))
        encoded = np.asarray(encoder.encode(windows, normalize_embeddings=True), dtype=float)
        if encoded.shape != (len(windows), EMBEDDING_DIMENSIONS):
            raise ValueError("unexpected prototype encoder output")
        vectors = [
            normalized_embedding(np.average(
                encoded[start:end], axis=0,
                weights=[len(window) for window in windows[start:end]],
            ))
            for start, end in spans
        ]
        return cls(catalog, np.asarray(vectors, dtype=float))

    @staticmethod
    def _terms(profile: Any) -> tuple[tuple[str, str, float], ...]:
        terms: dict[str, tuple[str, float]] = {}
        for item in profile.weighted_terms:
            display = str(item.term)
            canonical = canonicalize_personality_text(display)
            weight = float(item.weight)
            if not canonical or not np.isfinite(weight) or weight <= 0:
                raise ValueError("MBTI keywords must have positive finite weights")
            previous = terms.get(canonical)
            if previous is None or weight > previous[1]:
                terms[canonical] = (display, weight)
        return tuple((key, display, weight) for key, (display, weight) in terms.items())

    def affinity(self, text: str, semantic_vector: Sequence[float]) -> np.ndarray:
        query = canonicalize_personality_text(text)
        embedding = normalized_embedding(semantic_vector)
        semantic = np.clip(self.prototype_vectors @ embedding, 0, 1)
        coverage = np.zeros(MBTI_DIMENSIONS, dtype=float)
        for index, profile in enumerate(self.catalog.profiles):
            terms = self._terms(profile)
            total = sum(weight for _term, _display, weight in terms)
            if total:
                coverage[index] = sum(
                    weight for term, _display, weight in terms if term in query
                ) / total
        return np.clip(0.8 * semantic + 0.2 * coverage, 0, 1)

    def matched_terms(self, text: str, *, limit: int = 3) -> list[str]:
        """Return actual behavior words, never an inferred MBTI code."""

        query = canonicalize_personality_text(text)
        matched: dict[str, tuple[str, float]] = {}
        for profile in self.catalog.profiles:
            for term, display, weight in self._terms(profile):
                if term not in query or term.upper() in self.catalog.codes:
                    continue
                if term not in matched or weight > matched[term][1]:
                    matched[term] = (display, weight)
        return [
            display for _term, (display, _weight) in sorted(
                matched.items(), key=lambda item: (-item[1][1], item[0])
            )[:limit]
        ]

    def score_components(
        self,
        semantic: float,
        user_affinity: Sequence[float],
        pokemon_affinity: Sequence[float],
        *,
        mbti: str | None = None,
    ) -> dict[str, float | None]:
        semantic = float(np.clip(semantic, 0, 1))
        personality = cosine_affinity(user_affinity, pokemon_affinity)
        has_personality = (
            np.linalg.norm(user_affinity) > 0 and np.linalg.norm(pokemon_affinity) > 0
        )
        text_match = 0.75 * semantic + 0.25 * personality if has_personality else semantic
        mbti_score = None
        if mbti is not None:
            index = self.catalog.codes.index(mbti)
            mbti_score = float(np.clip(pokemon_affinity[index], 0, 1))
        total = text_match if mbti_score is None else 0.75 * text_match + 0.25 * mbti_score
        return {
            "semantic": round(semantic, 8),
            "personality": round(personality, 8),
            "mbti": round(mbti_score, 8) if mbti_score is not None else None,
            "total": round(float(np.clip(total, 0, 1)), 8),
        }
