"""Verify the public HTTPS endpoint after a production deployment."""

from __future__ import annotations

import argparse
import json
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


def _check(base_url: str, path: str, *, timeout: float) -> tuple[dict[str, object], object]:
    request = Request(urljoin(base_url.rstrip("/") + "/", path.lstrip("/")))
    request.add_header("User-Agent", "pokemon-production-smoke/1")
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
        return payload, response.headers


def _check_status(
    base_url: str,
    path: str,
    *,
    expected_status: int,
    timeout: float,
) -> None:
    request = Request(urljoin(base_url.rstrip("/") + "/", path.lstrip("/")))
    request.add_header("User-Agent", "pokemon-production-smoke/1")
    context = ssl.create_default_context()
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            status = response.status
    except HTTPError as exc:
        status = exc.code
    if status != expected_status:
        raise RuntimeError(
            f"{path} returned HTTP {status}; expected {expected_status}"
        )


def verify(base_url: str, *, attempts: int, interval: float, timeout: float) -> None:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            live, live_headers = _check(base_url, "/health/live", timeout=timeout)
            ready, _ready_headers = _check(base_url, "/health/ready", timeout=timeout)
            if live != {"status": "ok"}:
                raise RuntimeError("liveness response contract changed")
            if ready != {"status": "ready"}:
                raise RuntimeError("readiness response contract changed")
            if urlparse(base_url).scheme == "https":
                if not live_headers.get("Strict-Transport-Security"):
                    raise RuntimeError("HTTPS response is missing HSTS")
                if live_headers.get("X-Content-Type-Options") != "nosniff":
                    raise RuntimeError("HTTPS response is missing nosniff")
            _check_status(
                base_url,
                "/metrics",
                expected_status=404,
                timeout=timeout,
            )
            return
        except (HTTPError, URLError, TimeoutError, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(interval)
    raise RuntimeError(f"production smoke test failed after {attempts} attempts: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--allow-http", action="store_true")
    args = parser.parse_args()
    parsed = urlparse(args.base_url)
    if parsed.scheme not in ({"http", "https"} if args.allow_http else {"https"}):
        parser.error("--base-url must use HTTPS unless --allow-http is set")
    if not parsed.netloc or args.attempts < 1 or args.interval < 0 or args.timeout <= 0:
        parser.error("invalid smoke-test arguments")
    verify(
        args.base_url,
        attempts=args.attempts,
        interval=args.interval,
        timeout=args.timeout,
    )
    print("Production smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
