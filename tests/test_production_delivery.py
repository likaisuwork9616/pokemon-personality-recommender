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
        self.assertNotIn('"5432:5432"', compose)
        self.assertNotIn("build:", compose)
        self.assertIn("feedback-purge:", compose)
        self.assertIn("${FEEDBACK_RETENTION_DAYS:-90}", compose)

    def test_caddy_enforces_https_headers_and_live_upstream_checks(self):
        caddyfile = (ROOT / "ops" / "caddy" / "Caddyfile").read_text(encoding="utf-8")

        self.assertIn("{$PUBLIC_DOMAIN}", caddyfile)
        self.assertIn("Strict-Transport-Security", caddyfile)
        self.assertIn('X-Content-Type-Options "nosniff"', caddyfile)
        self.assertIn("health_uri /health/live", caddyfile)
        self.assertIn("reverse_proxy api:8000", caddyfile)

    def test_release_uses_immutable_digest_and_protected_self_hosted_runner(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("docker/build-push-action@v6", workflow)
        self.assertIn("${IMAGE_NAME}@${IMAGE_DIGEST}", workflow)
        self.assertIn("runs-on: [self-hosted, linux, x64, pokemon-production]", workflow)
        self.assertIn("environment: production", workflow)
        self.assertIn('sh scripts/production/deploy.sh "$APP_IMAGE"', workflow)

    def test_deployment_scripts_backup_smoke_test_and_gate_destructive_restore(self):
        deploy = (ROOT / "scripts" / "production" / "deploy.sh").read_text(encoding="utf-8")
        restore = (ROOT / "scripts" / "production" / "restore_postgres.sh").read_text(
            encoding="utf-8"
        )
        smoke = (ROOT / "scripts" / "production" / "smoke_test.py").read_text(
            encoding="utf-8"
        )

        self.assertLess(deploy.index("backup_postgres.sh"), deploy.index("run --rm migrate"))
        self.assertIn("rollback.sh", deploy)
        self.assertIn("--confirm-database-overwrite", restore)
        self.assertIn("Strict-Transport-Security", smoke)
        self.assertIn('"/health/ready"', smoke)


if __name__ == "__main__":
    unittest.main()
