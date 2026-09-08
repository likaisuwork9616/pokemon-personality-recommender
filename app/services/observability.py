"""Low-cardinality request telemetry that never inspects request bodies."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock


class RequestMetrics:
    DURATION_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: dict[tuple[str, str, int], int] = defaultdict(int)
        self._durations: dict[tuple[str, str], tuple[int, float]] = defaultdict(lambda: (0, 0.0))
        self._duration_buckets: dict[tuple[str, str], list[int]] = defaultdict(
            lambda: [0] * len(self.DURATION_BUCKETS)
        )
        self._personality_refresh_failures = 0

    def observe(self, method: str, route: str, status_code: int, duration_seconds: float) -> None:
        key = (method, route)
        with self._lock:
            self._counts[(method, route, status_code)] += 1
            count, total = self._durations[key]
            duration = max(0.0, duration_seconds)
            self._durations[key] = (count + 1, total + duration)
            buckets = self._duration_buckets[key]
            for index, upper_bound in enumerate(self.DURATION_BUCKETS):
                if duration <= upper_bound:
                    buckets[index] += 1

    def observe_personality_refresh_failure(self) -> None:
        """Count refresh failures without recording vocabulary or error details."""

        with self._lock:
            self._personality_refresh_failures += 1

    def render_prometheus(
        self,
        *,
        personality_refresh_healthy: bool | None = None,
    ) -> str:
        with self._lock:
            counts = dict(self._counts)
            durations = dict(self._durations)
            duration_buckets = {
                key: tuple(values) for key, values in self._duration_buckets.items()
            }
            personality_refresh_failures = self._personality_refresh_failures
        lines = [
            "# HELP pokemon_http_requests_total HTTP requests by method, route and status.",
            "# TYPE pokemon_http_requests_total counter",
        ]
        for (method, route, status_code), value in sorted(counts.items()):
            lines.append(f'pokemon_http_requests_total{{method="{method}",route="{route}",status="{status_code}"}} {value}')
        lines.extend([
            "# HELP pokemon_http_request_duration_seconds HTTP request duration by method and route.",
            "# TYPE pokemon_http_request_duration_seconds histogram",
        ])
        for (method, route), (count, total) in sorted(durations.items()):
            labels = f'method="{method}",route="{route}"'
            for upper_bound, bucket_count in zip(
                self.DURATION_BUCKETS,
                duration_buckets[(method, route)],
                strict=True,
            ):
                lines.append(
                    "pokemon_http_request_duration_seconds_bucket"
                    f'{{{labels},le="{upper_bound:g}"}} {bucket_count}'
                )
            lines.append(
                "pokemon_http_request_duration_seconds_bucket"
                f'{{{labels},le="+Inf"}} {count}'
            )
            lines.append(f"pokemon_http_request_duration_seconds_sum{{{labels}}} {total:.9f}")
            lines.append(f"pokemon_http_request_duration_seconds_count{{{labels}}} {count}")
        lines.extend([
            "# HELP pokemon_personality_refresh_failures_total Runtime personality vocabulary refresh failures.",
            "# TYPE pokemon_personality_refresh_failures_total counter",
            f"pokemon_personality_refresh_failures_total {personality_refresh_failures}",
        ])
        if personality_refresh_healthy is not None:
            lines.extend([
                "# HELP pokemon_personality_refresh_healthy Whether the runtime personality vocabulary snapshot is healthy.",
                "# TYPE pokemon_personality_refresh_healthy gauge",
                f"pokemon_personality_refresh_healthy {1 if personality_refresh_healthy else 0}",
            ])
        return "\n".join(lines) + "\n"
