"""Audit local artwork provenance and sample the current CDN delivery."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_POKEMON_COUNT = 1025
OFFICIAL_SOURCE_HOST = "tw.portal-pokemon.com"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        return [dict(row) for row in reader]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_local_records(
    source_rows: list[dict[str, str]],
    delivery_rows: list[dict[str, str]],
    *,
    images_dir: Path,
) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    if len(source_rows) != EXPECTED_POKEMON_COUNT:
        errors.append(
            f"source manifest has {len(source_rows)} rows; "
            f"expected {EXPECTED_POKEMON_COUNT}"
        )
    if len(delivery_rows) != EXPECTED_POKEMON_COUNT:
        errors.append(
            f"delivery result has {len(delivery_rows)} rows; "
            f"expected {EXPECTED_POKEMON_COUNT}"
        )

    delivery_by_number = {
        (row.get("pokedex_number") or "").strip(): row for row in delivery_rows
    }
    source_hosts: set[str] = set()
    delivery_hosts: set[str] = set()
    verified_local = 0
    verified_delivery_records = 0
    seen_numbers: set[int] = set()

    for row in source_rows:
        raw_number = (row.get("pokedex_number") or "").strip()
        try:
            number = int(raw_number)
        except ValueError:
            errors.append(f"invalid source pokedex_number: {raw_number!r}")
            continue
        if number in seen_numbers:
            errors.append(f"duplicate source pokedex_number: {number}")
            continue
        seen_numbers.add(number)

        source_url = (row.get("source_url") or "").strip()
        source_host = (urlsplit(source_url).hostname or "").casefold()
        source_hosts.add(source_host)
        if source_host != OFFICIAL_SOURCE_HOST:
            errors.append(f"No.{number:04d} has an unexpected source host")
        if (row.get("status") or "").strip() != "downloaded":
            errors.append(f"No.{number:04d} source was not recorded as downloaded")

        filename = (row.get("filename") or "").strip()
        local_path = images_dir / filename
        expected_hash = (row.get("sha256") or "").strip().casefold()
        if not local_path.is_file():
            errors.append(f"No.{number:04d} local artwork is missing")
        elif sha256_file(local_path) != expected_hash:
            errors.append(f"No.{number:04d} local SHA-256 mismatch")
        else:
            with local_path.open("rb") as handle:
                if handle.read(8) != PNG_SIGNATURE:
                    errors.append(f"No.{number:04d} local file is not PNG")
                else:
                    verified_local += 1

        delivery = delivery_by_number.get(raw_number)
        if delivery is None:
            errors.append(f"No.{number:04d} is missing from delivery results")
            continue
        delivery_url = (delivery.get("delivery_url") or "").strip()
        parsed_delivery = urlsplit(delivery_url)
        delivery_hosts.add((parsed_delivery.hostname or "").casefold())
        if parsed_delivery.scheme != "https":
            errors.append(f"No.{number:04d} delivery is not HTTPS")
        if not parsed_delivery.path.endswith(f"/{number:04d}.png"):
            errors.append(f"No.{number:04d} delivery path is inconsistent")
        if (delivery.get("sha256") or "").strip().casefold() != expected_hash:
            errors.append(f"No.{number:04d} delivery SHA-256 lineage mismatch")
        if (
            (delivery.get("s3_validation_status") or "").strip() == "verified"
            and (delivery.get("delivery_validation_status") or "").strip()
            == "verified"
        ):
            verified_delivery_records += 1
        else:
            errors.append(f"No.{number:04d} has no verified delivery record")

    expected_numbers = set(range(1, EXPECTED_POKEMON_COUNT + 1))
    if seen_numbers != expected_numbers:
        errors.append("source manifest must contain each number from 1 through 1025")
    if len(delivery_hosts) != 1 or not next(iter(delivery_hosts), "").endswith(
        ".cloudfront.net"
    ):
        errors.append("delivery results must use one CloudFront hostname")

    summary: dict[str, object] = {
        "source_rows": len(source_rows),
        "source_hosts": sorted(source_hosts),
        "local_png_sha256_verified": verified_local,
        "delivery_rows": len(delivery_rows),
        "delivery_hosts": sorted(delivery_hosts),
        "delivery_records_verified": verified_delivery_records,
    }
    return summary, errors


def fetch_delivery(url: str, timeout: float) -> tuple[bytes, str]:
    request = Request(
        url,
        headers={"User-Agent": "pokemon-artwork-audit/1", "Cache-Control": "no-cache"},
    )
    with urlopen(request, timeout=timeout) as response:
        content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0]
        return response.read(), content_type.strip().casefold()


def sample_delivery_rows(
    rows: list[dict[str, str]],
    *,
    sample_size: int,
    timeout: float,
    fetcher: Callable[[str, float], tuple[bytes, str]] = fetch_delivery,
) -> tuple[list[int], list[str]]:
    if sample_size < 0:
        raise ValueError("sample_size must not be negative")
    if not rows or sample_size == 0:
        return [], []
    count = min(sample_size, len(rows))
    indexes = (
        [0]
        if count == 1
        else [round(index * (len(rows) - 1) / (count - 1)) for index in range(count)]
    )
    verified: list[int] = []
    errors: list[str] = []
    for index in indexes:
        row = rows[index]
        number = int((row.get("pokedex_number") or "0").strip())
        try:
            payload, content_type = fetcher(
                (row.get("delivery_url") or "").strip(),
                timeout,
            )
            if content_type != "image/png":
                raise ValueError(f"unexpected content type {content_type!r}")
            if not payload.startswith(PNG_SIGNATURE):
                raise ValueError("response is not PNG")
            expected_hash = (row.get("sha256") or "").strip().casefold()
            if hashlib.sha256(payload).hexdigest() != expected_hash:
                raise ValueError("response SHA-256 mismatch")
            verified.append(number)
        except Exception as exc:
            errors.append(f"No.{number:04d}: {type(exc).__name__}: {exc}")
    return verified, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=PROJECT_ROOT / "pk_pic" / "_manifest.csv",
    )
    parser.add_argument(
        "--delivery-result",
        type=Path,
        default=(
            PROJECT_ROOT
            / "pk_pic"
            / "manifests"
            / "pokemon_image_upload_result.csv"
        ),
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=PROJECT_ROOT / "pk_pic",
    )
    parser.add_argument("--sample-size", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()

    source_rows = read_csv(args.source_manifest)
    delivery_rows = read_csv(args.delivery_result)
    summary, errors = audit_local_records(
        source_rows,
        delivery_rows,
        images_dir=args.images_dir,
    )
    if not args.offline:
        verified, network_errors = sample_delivery_rows(
            delivery_rows,
            sample_size=args.sample_size,
            timeout=args.timeout,
        )
        summary["live_sample_verified"] = verified
        errors.extend(network_errors)
    summary["status"] = "passed" if not errors else "failed"
    summary["errors"] = errors
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
