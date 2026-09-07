"""Low-cardinality request telemetry that never inspects request bodies."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock


class RequestMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: dict[tuple[str, str, int], int] = defaultdict(int)
        self._durations: dict[tuple[str, str], tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    def observe(self, method: str, route: str, status_code: int, duration_seconds: float) -> None:
        key = (method, route)
        with self._lock:
            self._counts[(method, route, status_code)] += 1
            count, total = self._durations[key]
            self._durations[key] = (count + 1, total + max(0.0, duration_seconds))

    def render_prometheus(self) -> str:
        with self._lock:
            counts = dict(self._counts)
            durations = dict(self._durations)
        lines = [
            "# HELP pokemon_http_requests_total HTTP requests by method, route and status.",
            "# TYPE pokemon_http_requests_total counter",
        ]
        for (method, route, status_code), value in sorted(counts.items()):
            lines.append(f'pokemon_http_requests_total{{method="{method}",route="{route}",status="{status_code}"}} {value}')
        lines.extend([
            "# HELP pokemon_http_request_duration_seconds_sum Total HTTP request duration.",
            "# TYPE pokemon_http_request_duration_seconds_sum counter",
            "# HELP pokemon_http_request_duration_seconds_count Observed HTTP requests.",
            "# TYPE pokemon_http_request_duration_seconds_count counter",
        ])
        for (method, route), (count, total) in sorted(durations.items()):
            labels = f'method="{method}",route="{route}"'
            lines.append(f"pokemon_http_request_duration_seconds_sum{{{labels}}} {total:.9f}")
            lines.append(f"pokemon_http_request_duration_seconds_count{{{labels}}} {count}")
        return "\n".join(lines) + "\n"
