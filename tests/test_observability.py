from __future__ import annotations

import io
import logging
import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.observability import RequestMetrics


class _Engine:
    @staticmethod
    def recommend(_text, top_k=3):
        return []


class ObservabilityTests(unittest.TestCase):
    def test_duration_histogram_exposes_cumulative_prometheus_buckets(self):
        metrics = RequestMetrics()
        metrics.observe("GET", "/example", 200, 0.02)
        metrics.observe("GET", "/example", 200, 0.7)

        rendered = metrics.render_prometheus()

        self.assertIn("# TYPE pokemon_http_request_duration_seconds histogram", rendered)
        self.assertIn('route="/example",le="0.01"} 0', rendered)
        self.assertIn('route="/example",le="0.025"} 1', rendered)
        self.assertIn('route="/example",le="0.5"} 1', rendered)
        self.assertIn('route="/example",le="1"} 2', rendered)
        self.assertIn('route="/example",le="+Inf"} 2', rendered)
    def test_request_id_and_prometheus_metrics_use_route_templates(self):
        with TestClient(create_app(_Engine)) as client:
            response = client.get("/api/v1/admin/pokemon/123456")
            metrics = client.get("/metrics")

        self.assertEqual(len(response.headers["x-request-id"]), 32)
        self.assertEqual(metrics.status_code, 200)
        self.assertIn("pokemon_http_requests_total", metrics.text)
        self.assertIn('route="/api/v1/admin/pokemon/{pokemon_id}"', metrics.text)
        self.assertNotIn("123456", metrics.text)

    def test_structured_request_log_never_contains_request_body(self):
        marker = "PRIVATE-OBSERVABILITY-MARKER"
        stream = io.StringIO()
        logger = logging.getLogger("pokemon.http")
        handler = logging.StreamHandler(stream)
        previous = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            with TestClient(create_app(_Engine)) as client:
                client.post("/api/v1/recommendations", json={"text": marker})
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous)

        output = stream.getvalue()
        self.assertIn('"event":"http_request"', output)
        self.assertNotIn(marker, output)
        self.assertNotIn('"body"', output)


if __name__ == "__main__":
    unittest.main()
