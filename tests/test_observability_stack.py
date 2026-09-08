from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ObservabilityStackTests(unittest.TestCase):
    def test_prometheus_scrapes_the_internal_api_metrics_endpoint(self):
        config = (ROOT / "ops" / "prometheus" / "prometheus.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("job_name: pokemon-api", config)
        self.assertIn("metrics_path: /metrics", config)
        self.assertIn("- api:8000", config)

    def test_grafana_dashboard_is_provisioned_with_actionable_promql(self):
        dashboard = json.loads(
            (ROOT / "ops" / "grafana" / "dashboards" / "pokemon-overview.json")
            .read_text(encoding="utf-8")
        )
        expressions = [
            target["expr"]
            for panel in dashboard["panels"]
            for target in panel.get("targets", [])
        ]

        self.assertEqual(dashboard["uid"], "pokemon-overview")
        self.assertTrue(any("pokemon_http_requests_total" in item for item in expressions))
        self.assertTrue(any("histogram_quantile(0.95" in item for item in expressions))
        self.assertTrue(any("status=~\"5..\"" in item for item in expressions))

        datasource = (
            ROOT
            / "ops"
            / "grafana"
            / "provisioning"
            / "datasources"
            / "prometheus.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("url: http://prometheus:9090", datasource)
        self.assertIn("uid: prometheus", datasource)

    def test_compose_pins_monitoring_images_and_persists_timeseries(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("prom/prometheus:v3.14.0", compose)
        self.assertIn("grafana/grafana:13.2.1", compose)
        self.assertIn("prometheus_data:/prometheus", compose)
        self.assertIn("grafana_data:/var/lib/grafana", compose)


if __name__ == "__main__":
    unittest.main()
