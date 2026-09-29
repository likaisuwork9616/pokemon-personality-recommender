"""In-process abuse protection for the public recommendation endpoint."""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import hashlib
import math
import os
import secrets
from threading import Lock
from time import monotonic
from typing import Callable


def _env_bool(value: str, *, name: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _env_int(
    values: dict[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(values.get(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class RecommendationRateLimitConfig:
    """Bounded public request and paid-explanation budgets."""

    enabled: bool = True
    recommendation_window_seconds: int = 60
    explanation_window_seconds: int = 600
    recommendations_per_client: int = 10
    explanations_per_client: int = 3
    explanations_global: int = 30
    max_tracked_clients: int = 10_000

    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
    ) -> "RecommendationRateLimitConfig":
        values = dict(os.environ if env is None else env)
        return cls(
            enabled=_env_bool(
                values.get("RECOMMENDATION_RATE_LIMIT_ENABLED", "true"),
                name="RECOMMENDATION_RATE_LIMIT_ENABLED",
            ),
            recommendation_window_seconds=_env_int(
                values,
                "RECOMMENDATION_RATE_LIMIT_WINDOW_SECONDS",
                60,
                minimum=1,
                maximum=86_400,
            ),
            explanation_window_seconds=_env_int(
                values,
                "EXPLANATION_RATE_LIMIT_WINDOW_SECONDS",
                600,
                minimum=1,
                maximum=86_400,
            ),
            recommendations_per_client=_env_int(
                values,
                "RECOMMENDATION_RATE_LIMIT_REQUESTS",
                10,
                minimum=1,
                maximum=10_000,
            ),
            explanations_per_client=_env_int(
                values,
                "EXPLANATION_RATE_LIMIT_REQUESTS",
                3,
                minimum=1,
                maximum=10_000,
            ),
            explanations_global=_env_int(
                values,
                "EXPLANATION_GLOBAL_RATE_LIMIT_REQUESTS",
                20,
                minimum=1,
                maximum=100_000,
            ),
            max_tracked_clients=_env_int(
                values,
                "RATE_LIMIT_MAX_TRACKED_CLIENTS",
                10_000,
                minimum=100,
                maximum=1_000_000,
            ),
        )


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int
    scope: str


@dataclass
class _ClientWindows:
    recommendations: deque[float]
    explanations: deque[float]
    last_seen: float


class RecommendationAbuseGuard:
    """Sliding-window limits without persisting or logging client addresses.

    The guard is deliberately process-local. The checked-in production setup
    runs one API process; deployments with multiple replicas should enforce an
    additional shared limit at the edge or through a shared data store.
    """

    def __init__(
        self,
        config: RecommendationRateLimitConfig,
        *,
        clock: Callable[[], float] = monotonic,
        hash_key: bytes | None = None,
    ) -> None:
        self.config = config
        self._clock = clock
        self._hash_key = hash_key or secrets.token_bytes(32)
        self._clients: OrderedDict[bytes, _ClientWindows] = OrderedDict()
        self._global_explanations: deque[float] = deque()
        self._lock = Lock()

    def check(
        self,
        client_identity: str,
        *,
        explanation_requested: bool,
    ) -> RateLimitDecision:
        if not self.config.enabled:
            return RateLimitDecision(True, 0, 0, 0, "disabled")

        now = self._clock()
        recommendation_cutoff = now - self.config.recommendation_window_seconds
        explanation_cutoff = now - self.config.explanation_window_seconds
        client_key = hashlib.blake2b(
            client_identity.encode("utf-8", errors="replace"),
            key=self._hash_key,
            digest_size=16,
        ).digest()

        with self._lock:
            self._prune_inactive_clients(
                min(recommendation_cutoff, explanation_cutoff)
            )
            windows = self._clients.get(client_key)
            if windows is None:
                if len(self._clients) >= self.config.max_tracked_clients:
                    self._clients.popitem(last=False)
                windows = _ClientWindows(deque(), deque(), now)
                self._clients[client_key] = windows
            else:
                windows.last_seen = now
                self._clients.move_to_end(client_key)

            self._prune(windows.recommendations, recommendation_cutoff)
            self._prune(windows.explanations, explanation_cutoff)
            self._prune(self._global_explanations, explanation_cutoff)

            if len(windows.recommendations) >= self.config.recommendations_per_client:
                return self._denied(
                    windows.recommendations,
                    now,
                    self.config.recommendations_per_client,
                    self.config.recommendation_window_seconds,
                    "client_recommendations",
                )
            if (
                explanation_requested
                and len(windows.explanations) >= self.config.explanations_per_client
            ):
                return self._denied(
                    windows.explanations,
                    now,
                    self.config.explanations_per_client,
                    self.config.explanation_window_seconds,
                    "client_explanations",
                )
            if (
                explanation_requested
                and len(self._global_explanations) >= self.config.explanations_global
            ):
                return self._denied(
                    self._global_explanations,
                    now,
                    self.config.explanations_global,
                    self.config.explanation_window_seconds,
                    "global_explanations",
                )

            windows.recommendations.append(now)
            remaining = (
                self.config.recommendations_per_client
                - len(windows.recommendations)
            )
            limit = self.config.recommendations_per_client
            scope = "client_recommendations"
            if explanation_requested:
                windows.explanations.append(now)
                self._global_explanations.append(now)
                explanation_remaining = min(
                    self.config.explanations_per_client - len(windows.explanations),
                    self.config.explanations_global - len(self._global_explanations),
                )
                if explanation_remaining < remaining:
                    remaining = explanation_remaining
                    limit = self.config.explanations_per_client
                    scope = "client_explanations"
            return RateLimitDecision(True, limit, max(0, remaining), 0, scope)

    def _denied(
        self,
        timestamps: deque[float],
        now: float,
        limit: int,
        window_seconds: int,
        scope: str,
    ) -> RateLimitDecision:
        retry_after = max(
            1,
            math.ceil(timestamps[0] + window_seconds - now),
        )
        return RateLimitDecision(False, limit, 0, retry_after, scope)

    @staticmethod
    def _prune(timestamps: deque[float], cutoff: float) -> None:
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()

    def _prune_inactive_clients(self, cutoff: float) -> None:
        while self._clients:
            _key, windows = next(iter(self._clients.items()))
            if windows.last_seen > cutoff:
                break
            self._clients.popitem(last=False)
