from __future__ import annotations

import copy
import unittest

from scripts.production.audit_compose_exposure import (
    ExposureAuditError,
    audit_config,
)


def _valid_config() -> dict[str, object]:
    return {
        "services": {
            "db": {"networks": {"data": None}},
            "api": {
                "command": [
                    "uvicorn",
                    "app.main:app",
                    "--forwarded-allow-ips=172.30.250.2",
                ],
                "networks": {
                    "edge": None,
                    "data": None,
                    "observability": None,
                },
            },
            "caddy": {
                "ports": [
                    {"target": 80},
                    {"target": 443, "protocol": "tcp"},
                    {"target": 443, "protocol": "udp"},
                ],
                "networks": {"edge": {"ipv4_address": "172.30.250.2"}},
            },
            "prometheus": {
                "ports": [{"host_ip": "127.0.0.1", "target": 9090}],
                "networks": {"observability": None},
            },
            "grafana": {
                "ports": [{"host_ip": "127.0.0.1", "target": 3000}],
                "networks": {"observability": None},
            },
            "alertmanager": {
                "ports": [{"host_ip": "127.0.0.1", "target": 9093}],
                "networks": {
                    "observability": None,
                    "notification-egress": None,
                },
            },
            "worker": {"networks": {"data": None, "model-egress": None}},
        },
        "networks": {
            "edge": {"ipam": {"config": [{"subnet": "172.30.250.0/29"}]}},
            "data": {"internal": True},
            "observability": {"internal": True},
            "model-egress": {},
            "notification-egress": {},
        },
    }


class ComposeExposureAuditTests(unittest.TestCase):
    def test_hardened_config_passes(self):
        audit_config(_valid_config())

    def test_database_or_api_host_port_is_rejected(self):
        for service in ("db", "api"):
            with self.subTest(service=service):
                config = copy.deepcopy(_valid_config())
                config["services"][service]["ports"] = [{"target": 5432}]
                with self.assertRaisesRegex(ExposureAuditError, "must not publish"):
                    audit_config(config)

    def test_operations_port_must_be_loopback_only(self):
        config = _valid_config()
        config["services"]["prometheus"]["ports"][0]["host_ip"] = "0.0.0.0"

        with self.assertRaisesRegex(ExposureAuditError, "loopback only"):
            audit_config(config)

    def test_wildcard_forwarded_proxy_trust_is_rejected(self):
        config = _valid_config()
        config["services"]["api"]["command"][-1] = "--forwarded-allow-ips=*"

        with self.assertRaisesRegex(ExposureAuditError, "every source"):
            audit_config(config)

    def test_private_network_regression_is_rejected(self):
        config = _valid_config()
        config["networks"]["data"]["internal"] = False

        with self.assertRaisesRegex(ExposureAuditError, "must be internal"):
            audit_config(config)

    def test_edge_subnet_regression_is_rejected(self):
        config = _valid_config()
        config["networks"]["edge"]["ipam"]["config"][0]["subnet"] = "172.30.0.0/16"

        with self.assertRaisesRegex(ExposureAuditError, "audited /29"):
            audit_config(config)


if __name__ == "__main__":
    unittest.main()
