"""Fail deployment if the rendered production Compose config exposes private services."""

from __future__ import annotations

import json
import sys
from typing import Any, Mapping


class ExposureAuditError(ValueError):
    """Rendered Compose configuration violates the production network policy."""


def _service(config: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    services = config.get("services")
    if not isinstance(services, Mapping) or not isinstance(services.get(name), Mapping):
        raise ExposureAuditError(f"required service is missing: {name}")
    return services[name]


def _network_names(service: Mapping[str, Any]) -> set[str]:
    networks = service.get("networks", {})
    if isinstance(networks, Mapping):
        return {str(name) for name in networks}
    if isinstance(networks, list):
        return {str(name) for name in networks}
    raise ExposureAuditError("service networks must be a mapping or list")


def _port_host_and_target(binding: Any) -> tuple[str | None, int]:
    if isinstance(binding, Mapping):
        host_ip = binding.get("host_ip")
        target = binding.get("target")
        try:
            return (str(host_ip) if host_ip else None, int(target))
        except (TypeError, ValueError) as exc:
            raise ExposureAuditError("invalid structured port binding") from exc
    if isinstance(binding, str):
        value = binding.rsplit("/", 1)[0]
        parts = value.rsplit(":", 2)
        try:
            if len(parts) == 3:
                return parts[0].strip('[]"') or None, int(parts[2])
            if len(parts) == 2:
                return None, int(parts[1])
            return None, int(parts[0])
        except ValueError as exc:
            raise ExposureAuditError("invalid string port binding") from exc
    raise ExposureAuditError("unknown port binding format")


def audit_config(config: Mapping[str, Any]) -> None:
    """Enforce that only Caddy is public and proxy trust has one source IP."""

    for name in ("db", "api"):
        if _service(config, name).get("ports"):
            raise ExposureAuditError(f"{name} must not publish host ports")

    expected_operations_ports = {
        "prometheus": 9090,
        "grafana": 3000,
        "alertmanager": 9093,
    }
    for name, expected_target in expected_operations_ports.items():
        bindings = _service(config, name).get("ports", [])
        if len(bindings) != 1:
            raise ExposureAuditError(f"{name} must publish exactly one loopback port")
        host_ip, target = _port_host_and_target(bindings[0])
        if host_ip != "127.0.0.1" or target != expected_target:
            raise ExposureAuditError(f"{name} must bind {expected_target} to loopback only")

    caddy_bindings = _service(config, "caddy").get("ports", [])
    caddy_targets = {_port_host_and_target(item)[1] for item in caddy_bindings}
    if caddy_targets != {80, 443}:
        raise ExposureAuditError("Caddy may publish only HTTP/HTTPS ports")

    allowed_publishers = {"caddy", *expected_operations_ports}
    services = config.get("services", {})
    for name, service in services.items():
        if name not in allowed_publishers and service.get("ports"):
            raise ExposureAuditError(f"unexpected published ports on {name}")

    command = [str(item) for item in _service(config, "api").get("command", [])]
    if "--forwarded-allow-ips=*" in command:
        raise ExposureAuditError("API must not trust forwarded headers from every source")
    if "--forwarded-allow-ips=172.30.250.2" not in command:
        raise ExposureAuditError("API must trust only the fixed Caddy edge address")

    expected_networks = {
        "db": {"data"},
        "caddy": {"edge"},
        "api": {"edge", "data", "observability"},
        "prometheus": {"observability"},
        "grafana": {"observability"},
        "alertmanager": {"observability", "notification-egress"},
    }
    for name, expected in expected_networks.items():
        actual = _network_names(_service(config, name))
        if actual != expected:
            raise ExposureAuditError(
                f"{name} networks are {sorted(actual)}; expected {sorted(expected)}"
            )

    networks = config.get("networks")
    if not isinstance(networks, Mapping):
        raise ExposureAuditError("top-level networks are missing")
    for name in ("data", "observability"):
        network = networks.get(name)
        if not isinstance(network, Mapping) or network.get("internal") is not True:
            raise ExposureAuditError(f"{name} network must be internal")

    edge_network = networks.get("edge")
    edge_ipam = edge_network.get("ipam", {}) if isinstance(edge_network, Mapping) else {}
    edge_configs = edge_ipam.get("config", []) if isinstance(edge_ipam, Mapping) else []
    if not any(
        isinstance(item, Mapping) and item.get("subnet") == "172.30.250.0/29"
        for item in edge_configs
    ):
        raise ExposureAuditError("edge network must keep the audited /29 subnet")

    caddy_network = _service(config, "caddy").get("networks", {}).get("edge", {})
    if caddy_network.get("ipv4_address") != "172.30.250.2":
        raise ExposureAuditError("Caddy must keep its audited fixed edge address")


def main() -> int:
    try:
        config = json.load(sys.stdin)
        audit_config(config)
    except (json.JSONDecodeError, ExposureAuditError) as exc:
        print(f"Production exposure audit failed: {exc}", file=sys.stderr)
        return 1
    print("Production exposure audit passed: only Caddy is public.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
