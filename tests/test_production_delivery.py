from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProductionDeliveryTests(unittest.TestCase):
    def test_production_compose_exposes_only_https_and_loopback_operations(self):
        compose = (ROOT / "compose.production.yml").read_text(encoding="utf-8")

        self.assertIn("${APP_IMAGE:?Set APP_IMAGE to an immutable GHCR digest}", compose)
        self.assertIn('ADMIN_COOKIE_SECURE: "true"', compose)
        self.assertIn('"80:80"', compose)
        self.assertIn('"443:443"', compose)
        self.assertIn('"127.0.0.1:${PROMETHEUS_PORT:-9090}:9090"', compose)
        self.assertIn('"127.0.0.1:${GRAFANA_PORT:-3000}:3000"', compose)
        self.assertIn('"127.0.0.1:${ALERTMANAGER_PORT:-9093}:9093"', compose)
        self.assertNotIn('"5432:5432"', compose)
        self.assertNotIn('"0.0.0.0:${PROMETHEUS_PORT', compose)
        self.assertNotIn('"0.0.0.0:${GRAFANA_PORT', compose)
        self.assertNotIn('"0.0.0.0:${ALERTMANAGER_PORT', compose)
        self.assertNotIn("build:", compose)
        self.assertIn("feedback-purge:", compose)
        self.assertIn("${FEEDBACK_RETENTION_DAYS:-90}", compose)

    def test_production_alert_receiver_is_external_and_aws_budget_is_bounded(self):
        compose = (ROOT / "compose.production.yml").read_text(encoding="utf-8")
        budget = (ROOT / "ops" / "aws" / "artwork-budget.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("${ALERTMANAGER_CONFIG_FILE:?Set ALERTMANAGER_CONFIG_FILE}", compose)
        self.assertNotIn("alertmanager.example.yml:/etc/alertmanager", compose)
        self.assertIn("AWS::Budgets::Budget", budget)
        self.assertIn("Amazon CloudFront", budget)
        self.assertIn("Amazon Simple Storage Service", budget)
        self.assertIn("Threshold: 50", budget)
        self.assertIn("Threshold: 80", budget)
        self.assertIn("Threshold: 100", budget)
        self.assertIn("Address: !Ref AlertEmail", budget)
        prometheus_block = compose[
            compose.index("\n  prometheus:"):compose.index("\n  alertmanager:")
        ]
        alertmanager_block = compose[
            compose.index("\n  alertmanager:"):compose.index("\n  grafana:")
        ]
        self.assertNotIn("condition: service_healthy", prometheus_block)
        self.assertIn('user: "65534:65534"', alertmanager_block)

    def test_caddy_enforces_https_headers_and_live_upstream_checks(self):
        caddyfile = (ROOT / "ops" / "caddy" / "Caddyfile").read_text(encoding="utf-8")

        self.assertIn("{$PUBLIC_DOMAIN}", caddyfile)
        self.assertIn("Strict-Transport-Security", caddyfile)
        self.assertIn('X-Content-Type-Options "nosniff"', caddyfile)
        self.assertIn("health_uri /health/live", caddyfile)
        self.assertIn("reverse_proxy api:8000", caddyfile)
        self.assertIn("@private_metrics path /metrics /metrics/*", caddyfile)
        self.assertIn("respond @private_metrics 404", caddyfile)
        self.assertIn("max_size 16KB", caddyfile)

    def test_quick_tunnel_keeps_secrets_empty_and_routes_through_caddy(self):
        compose = (ROOT / "compose.quick-tunnel.yml").read_text(encoding="utf-8")
        smoke = (
            ROOT / "scripts" / "production" / "quick_tunnel_smoke.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn('GEMINI_API_KEY: ""', compose)
        self.assertIn('OPENAI_API_KEY: ""', compose)
        self.assertIn('HF_TOKEN: ""', compose)
        self.assertIn("./ops/caddy/Caddyfile:/etc/caddy/Caddyfile:ro", compose)
        self.assertIn('"http://caddy:8080"', compose)
        self.assertNotIn('"http://api:8000"', compose)
        self.assertIn('"127.0.0.1:${TUNNEL_ORIGIN_PORT:-18080}:8080"', compose)
        self.assertIn("cloudflare/cloudflared:2026.9.3@sha256:", compose)
        self.assertIn(".trycloudflare.com", smoke)
        self.assertIn('Path "/metrics"', smoke)
        self.assertIn('"X-Forwarded-For"', smoke)
        self.assertIn('"X-Real-IP"', smoke)
        self.assertNotIn('"CF-Connecting-IP"', smoke)
        self.assertIn('provider -ne "local"', smoke)
        self.assertIn("used_fallback", smoke)

    def test_proxy_trust_and_service_networks_are_narrow(self):
        compose = (ROOT / "compose.production.yml").read_text(encoding="utf-8")

        self.assertNotIn("--forwarded-allow-ips=*", compose)
        self.assertIn("--forwarded-allow-ips=172.30.250.2", compose)
        self.assertIn("ipv4_address: 172.30.250.2", compose)
        self.assertIn("subnet: 172.30.250.0/29", compose)
        self.assertIn("data:\n    internal: true", compose)
        self.assertIn("observability:\n    internal: true", compose)
        self.assertIn("- model-egress", compose)
        self.assertIn("- notification-egress", compose)

    def test_release_uses_immutable_digest_and_protected_self_hosted_runner(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("docker/build-push-action@v6", workflow)
        self.assertIn("${IMAGE_NAME}@${IMAGE_DIGEST}", workflow)
        self.assertIn("runs-on: [self-hosted, linux, x64, pokemon-production]", workflow)
        self.assertIn("environment: production", workflow)
        self.assertIn('sh scripts/production/deploy.sh "$APP_IMAGE"', workflow)
        self.assertIn("ALERTMANAGER_CONFIG_FILE", workflow)

    def test_deployment_scripts_backup_smoke_test_and_gate_destructive_restore(self):
        deploy = (ROOT / "scripts" / "production" / "deploy.sh").read_text(encoding="utf-8")
        restore = (ROOT / "scripts" / "production" / "restore_postgres.sh").read_text(
            encoding="utf-8"
        )
        backup = (ROOT / "scripts" / "production" / "backup_postgres.sh").read_text(
            encoding="utf-8"
        )
        smoke = (ROOT / "scripts" / "production" / "smoke_test.py").read_text(
            encoding="utf-8"
        )

        self.assertLess(deploy.index("backup_postgres.sh"), deploy.index("run --rm migrate"))
        self.assertIn("rollback.sh", deploy)
        self.assertIn("--confirm-database-overwrite", restore)
        self.assertIn("sha256sum -c", restore)
        self.assertIn("pg_restore --list", restore)
        self.assertIn("--single-transaction", restore)
        self.assertIn("trap restart_services", restore)
        self.assertIn("umask 077", backup)
        self.assertIn("pg_restore --list", backup)
        self.assertIn("BACKUP_RETENTION_DAYS", backup)
        self.assertIn(".tmp", backup)
        self.assertIn("Strict-Transport-Security", smoke)
        self.assertIn('"/health/ready"', smoke)
        self.assertIn('live != {"status": "ok"}', smoke)
        self.assertIn('"/metrics"', smoke)
        self.assertIn("expected_status=404", smoke)
        self.assertIn("audit_compose_exposure.py", deploy)
        self.assertIn("alertmanager prometheus grafana caddy", deploy)

    def test_daily_maintenance_timer_is_persistent_and_runs_bounded_tasks(self):
        service = (ROOT / "ops" / "systemd" / "pokemon-maintenance.service").read_text(
            encoding="utf-8"
        )
        timer = (ROOT / "ops" / "systemd" / "pokemon-maintenance.timer").read_text(
            encoding="utf-8"
        )
        maintenance = (
            ROOT / "scripts" / "production" / "maintenance.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("EnvironmentFile=/etc/pokemon-recommender/production.env", service)
        self.assertIn("NoNewPrivileges=true", service)
        self.assertIn("Persistent=true", timer)
        self.assertIn("backup_postgres.sh", maintenance)
        self.assertIn("run --rm feedback-purge", maintenance)


if __name__ == "__main__":
    unittest.main()
