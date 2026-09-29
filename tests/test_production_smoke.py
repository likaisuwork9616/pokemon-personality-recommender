from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import unittest

from scripts.production.smoke_test import verify


class _Handler(BaseHTTPRequestHandler):
    metrics_status = 404

    def do_GET(self):
        if self.path == "/health/live":
            self._json(200, {"status": "ok"})
        elif self.path == "/health/ready":
            self._json(200, {"status": "ready"})
        elif self.path == "/metrics":
            self.send_response(self.metrics_status)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, status: int, payload: dict[str, str]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


class ProductionSmokeTests(unittest.TestCase):
    def setUp(self):
        _Handler.metrics_status = 404
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_accepts_live_ready_and_private_metrics_contract(self):
        verify(self.base_url, attempts=1, interval=0, timeout=1)

    def test_rejects_public_metrics_endpoint(self):
        _Handler.metrics_status = 200

        with self.assertRaisesRegex(RuntimeError, "expected 404"):
            verify(self.base_url, attempts=1, interval=0, timeout=1)


if __name__ == "__main__":
    unittest.main()
