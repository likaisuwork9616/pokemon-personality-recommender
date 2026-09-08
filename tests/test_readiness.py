from __future__ import annotations

import time
import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.readiness import DatabaseReadinessProbe, ReadinessConfig


class _Engine:
    personality_refresh_healthy = True


class _Probe:
    def __init__(self, results) -> None:
        self.results = iter(results)
        self.calls = 0

    def check(self):
        self.calls += 1
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


class ReadinessTests(unittest.TestCase):
    def test_every_readiness_request_performs_a_fresh_database_probe(self):
        probe = _Probe([True, False])
        application = create_app(
            _Engine,
            database_readiness_probe=probe,
            readiness_config=ReadinessConfig(database_timeout_seconds=0.2),
        )

        with TestClient(application) as client:
            healthy = client.get("/health/ready")
            unhealthy = client.get("/health/ready")
            live = client.get("/health/live")
            metrics = client.get("/metrics").text

        self.assertEqual(healthy.json(), {"status": "ready"})
        self.assertEqual(unhealthy.status_code, 503)
        self.assertEqual(unhealthy.json()["reason"], "database_unavailable")
        self.assertEqual(live.status_code, 200)
        self.assertEqual(probe.calls, 2)
        self.assertIn('pokemon_readiness_database_checks_total{outcome="success"} 1', metrics)
        self.assertIn('pokemon_readiness_database_checks_total{outcome="failure"} 1', metrics)
        self.assertIn("pokemon_readiness_database_healthy 0", metrics)

    def test_database_probe_timeout_is_bounded_and_observable(self):
        class SlowProbe:
            @staticmethod
            def check():
                time.sleep(0.3)
                return True

        application = create_app(
            _Engine,
            database_readiness_probe=SlowProbe(),
            readiness_config=ReadinessConfig(database_timeout_seconds=0.05),
        )

        with TestClient(application) as client:
            started = time.perf_counter()
            response = client.get("/health/ready")
            elapsed = time.perf_counter() - started
            metrics = client.get("/metrics").text

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["reason"], "database_unavailable")
        self.assertLess(elapsed, 0.2)
        self.assertIn('pokemon_readiness_database_checks_total{outcome="timeout"} 1', metrics)

    def test_database_probe_executes_select_one_in_a_closed_session_scope(self):
        class Result:
            @staticmethod
            def scalar_one():
                return 1

        class Session:
            def __init__(self) -> None:
                self.closed = False
                self.statements = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.closed = True

            def execute(self, statement):
                self.statements.append(str(statement))
                return Result()

        session = Session()
        probe = DatabaseReadinessProbe(lambda: session)

        self.assertTrue(probe.check())
        self.assertEqual(session.statements, ["SELECT 1"])
        self.assertTrue(session.closed)

    def test_readiness_timeout_configuration_is_strict(self):
        self.assertEqual(
            ReadinessConfig.from_env({"READINESS_DB_TIMEOUT_SECONDS": "0.5"})
            .database_timeout_seconds,
            0.5,
        )
        for value in ("invalid", "0.01", "11"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ReadinessConfig.from_env({"READINESS_DB_TIMEOUT_SECONDS": value})


if __name__ == "__main__":
    unittest.main()
