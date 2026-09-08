"""Optional bounded Cross-Encoder reranking with deterministic fallback."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp
import os
from threading import Lock
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

import numpy as np


DEFAULT_CROSS_ENCODER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


@dataclass(frozen=True)
class CrossEncoderConfig:
    enabled: bool = False
    model_name: str = DEFAULT_CROSS_ENCODER_MODEL
    candidate_limit: int = 10
    weight: float = 0.25
    latency_budget_ms: float = 250.0
    batch_size: int = 10
    max_length: int = 256

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ValueError("CROSS_ENCODER_MODEL must not be blank")
        if not 3 <= self.candidate_limit <= 50:
            raise ValueError("CROSS_ENCODER_CANDIDATE_LIMIT must be between 3 and 50")
        if not 0 < self.weight <= 0.5:
            raise ValueError("CROSS_ENCODER_WEIGHT must be greater than 0 and at most 0.5")
        if not 10 <= self.latency_budget_ms <= 5000:
            raise ValueError("CROSS_ENCODER_LATENCY_BUDGET_MS must be between 10 and 5000")
        if not 1 <= self.batch_size <= 50:
            raise ValueError("CROSS_ENCODER_BATCH_SIZE must be between 1 and 50")
        if not 64 <= self.max_length <= 512:
            raise ValueError("CROSS_ENCODER_MAX_LENGTH must be between 64 and 512")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "CrossEncoderConfig":
        values = env if env is not None else os.environ
        enabled_value = values.get("CROSS_ENCODER_ENABLED", "false").strip().casefold()
        if enabled_value not in {"true", "false", "1", "0"}:
            raise ValueError("CROSS_ENCODER_ENABLED must be true or false")
        try:
            return cls(
                enabled=enabled_value in {"true", "1"},
                model_name=values.get("CROSS_ENCODER_MODEL", DEFAULT_CROSS_ENCODER_MODEL),
                candidate_limit=int(values.get("CROSS_ENCODER_CANDIDATE_LIMIT", "10")),
                weight=float(values.get("CROSS_ENCODER_WEIGHT", "0.25")),
                latency_budget_ms=float(values.get("CROSS_ENCODER_LATENCY_BUDGET_MS", "250")),
                batch_size=int(values.get("CROSS_ENCODER_BATCH_SIZE", "10")),
                max_length=int(values.get("CROSS_ENCODER_MAX_LENGTH", "256")),
            )
        except ValueError as exc:
            if str(exc).startswith("CROSS_ENCODER_"):
                raise
            raise ValueError("invalid Cross-Encoder environment configuration") from exc


@dataclass(frozen=True)
class RerankOutcome:
    candidates: tuple[dict[str, Any], ...]
    elapsed_ms: float
    applied: bool
    reason: str


class CrossEncoderReranker:
    """Score query/evidence pairs and blend them with the stable base score."""

    def __init__(
        self,
        config: CrossEncoderConfig,
        *,
        predictor: Any | None = None,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        if not config.enabled:
            raise ValueError("cannot construct a disabled Cross-Encoder reranker")
        self.config = config
        self._clock = clock
        self._predict_lock = Lock()
        if predictor is None:
            from sentence_transformers import CrossEncoder

            predictor = CrossEncoder(
                config.model_name,
                max_length=config.max_length,
            )
        self._predictor = predictor

    def rerank(
        self,
        query_text: str,
        candidates: Sequence[dict[str, Any]],
    ) -> RerankOutcome:
        bounded = tuple(candidates[: self.config.candidate_limit])
        if len(bounded) < 3:
            return RerankOutcome(bounded, 0.0, False, "insufficient_candidates")
        pairs = [(query_text, self._evidence_text(candidate)) for candidate in bounded]
        started = self._clock()
        try:
            with self._predict_lock:
                raw_scores = self._predictor.predict(
                    pairs,
                    batch_size=self.config.batch_size,
                    show_progress_bar=False,
                )
            scores = np.asarray(raw_scores, dtype=float).reshape(-1)
            if scores.shape != (len(bounded),) or not np.isfinite(scores).all():
                raise ValueError("invalid Cross-Encoder scores")
        except Exception:
            elapsed_ms = max(0.0, (self._clock() - started) * 1000.0)
            return RerankOutcome(bounded, elapsed_ms, False, "prediction_failed")
        elapsed_ms = max(0.0, (self._clock() - started) * 1000.0)
        if elapsed_ms > self.config.latency_budget_ms:
            return RerankOutcome(bounded, elapsed_ms, False, "latency_budget_exceeded")

        rescored: list[tuple[float, float, int, dict[str, Any]]] = []
        for base_position, (candidate, raw_score) in enumerate(
            zip(bounded, scores, strict=True)
        ):
            cross_encoder_score = self._sigmoid(float(raw_score))
            base_score = float(candidate["scores"]["total"])
            total = (
                (1.0 - self.config.weight) * base_score
                + self.config.weight * cross_encoder_score
            )
            updated = {
                **candidate,
                "scores": {
                    **candidate["scores"],
                    "pre_rerank_total": round(base_score, 8),
                    "reranker": round(cross_encoder_score, 8),
                    "total": round(total, 8),
                },
            }
            rescored.append((-total, -base_score, base_position, updated))
        rescored.sort(key=lambda item: item[:3])
        return RerankOutcome(
            tuple(item[3] for item in rescored),
            elapsed_ms,
            True,
            "applied",
        )

    @staticmethod
    def _evidence_text(candidate: Mapping[str, Any]) -> str:
        evidence = candidate.get("matching_evidence", ())
        parts = [
            str(item.get("text", "")).strip()
            for item in evidence
            if str(item.get("text", "")).strip()
        ]
        return "\n".join(parts)[:1500]

    @staticmethod
    def _sigmoid(value: float) -> float:
        if value >= 0:
            return 1.0 / (1.0 + exp(-min(value, 60.0)))
        exponent = exp(max(value, -60.0))
        return exponent / (1.0 + exponent)
