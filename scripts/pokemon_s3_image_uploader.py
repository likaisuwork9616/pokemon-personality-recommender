"""Safely upload a validated Pokemon image manifest to Amazon S3.

Without ``--execute`` this command performs local validation only.  It never
overwrites an S3 object whose size or SHA-256 metadata differs from the local
file.  Result rows are checkpointed atomically and can be resumed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "pk_pic" / "manifests" / "pokemon_image_upload_manifest.csv"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "pk_pic" / "manifests" / "pokemon_image_upload_result.csv"
)
EXPECTED_POKEMON_COUNT = 1025
SUCCESS_STATUSES = {"uploaded", "already_exists"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
RESULT_COLUMNS = (
    "s3_validation_status",
    "s3_verified_at",
    "s3_error",
    "delivery_validation_status",
    "delivery_verified_at",
    "delivery_error",
)
REQUIRED_COLUMNS = {
    "image_id",
    "pokedex_number",
    "name_zh",
    "source",
    "image_role",
    "original_image_path",
    "file_size_bytes",
    "sha256",
    "bucket",
    "region",
    "object_key",
    "content_type",
    "validation_status",
    "upload_status",
    "s3_uri",
    "s3_https_url",
    "delivery_url",
}


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("manifest has no header")
        return [dict(row) for row in reader], list(reader.fieldnames)


def add_result_columns(fieldnames: list[str]) -> list[str]:
    result = list(fieldnames)
    for column in RESULT_COLUMNS:
        if column not in result:
            result.append(column)
    return result


def write_csv_safely(
    path: Path, rows: list[dict[str, str]], fieldnames: list[str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def resolve_local_path(project_root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def validate_manifest(
    rows: list[dict[str, str]],
    *,
    project_root: Path,
    bucket: str,
    region: str,
    required_prefix: str,
    delivery_base_url: str,
) -> list[str]:
    if len(rows) != EXPECTED_POKEMON_COUNT:
        return [f"manifest must contain {EXPECTED_POKEMON_COUNT} rows, got {len(rows)}"]
    missing_columns = REQUIRED_COLUMNS - set(rows[0])
    if missing_columns:
        return [f"manifest is missing columns: {', '.join(sorted(missing_columns))}"]

    errors: list[str] = []
    seen_numbers: set[int] = set()
    seen_keys: set[str] = set()
    normalized_prefix = required_prefix.strip().strip("/") + "/"
    normalized_delivery = delivery_base_url.strip().rstrip("/")
    key_pattern = re.compile(rf"^{re.escape(normalized_prefix)}(?P<number>\d{{4}})\.png$")

    for position, row in enumerate(rows, start=2):
        label = clean(row.get("image_id")) or f"CSV row {position}"
        try:
            number = int(clean(row.get("pokedex_number")))
        except ValueError:
            errors.append(f"{label}: invalid pokedex_number")
            continue
        if number in seen_numbers:
            errors.append(f"{label}: duplicate pokedex_number {number}")
        seen_numbers.add(number)

        object_key = clean(row.get("object_key"))
        key_match = key_pattern.fullmatch(object_key)
        if not key_match or int(key_match.group("number")) != number:
            errors.append(f"{label}: object_key does not match pokedex_number")
        if object_key in seen_keys:
            errors.append(f"{label}: duplicate object_key")
        seen_keys.add(object_key)

        expected_delivery = f"{normalized_delivery}/{object_key}"
        checks = (
            (clean(row.get("bucket")) == bucket, "bucket mismatch"),
            (clean(row.get("region")) == region, "region mismatch"),
            (clean(row.get("source")) == "pokemon_official_tw", "source mismatch"),
            (clean(row.get("image_role")) == "artwork", "image_role mismatch"),
            (clean(row.get("content_type")) == "image/png", "content_type mismatch"),
            (clean(row.get("validation_status")) == "ready", "row is not ready"),
            (clean(row.get("delivery_url")) == expected_delivery, "delivery URL mismatch"),
        )
        errors.extend(f"{label}: {message}" for valid, message in checks if not valid)

        local_path = resolve_local_path(project_root, clean(row.get("original_image_path")))
        if not local_path.is_file():
            errors.append(f"{label}: local image is missing: {local_path}")
            continue
        try:
            expected_size = int(clean(row.get("file_size_bytes")))
        except ValueError:
            expected_size = -1
        if local_path.stat().st_size != expected_size:
            errors.append(f"{label}: local file size mismatch")
        expected_hash = clean(row.get("sha256")).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            errors.append(f"{label}: invalid SHA-256")
        elif sha256_file(local_path) != expected_hash:
            errors.append(f"{label}: local SHA-256 mismatch")
        with local_path.open("rb") as handle:
            if handle.read(8) != PNG_SIGNATURE:
                errors.append(f"{label}: local file is not PNG")

    expected_numbers = set(range(1, EXPECTED_POKEMON_COUNT + 1))
    if seen_numbers != expected_numbers:
        errors.append("manifest must contain each pokedex_number from 1 through 1025")
    return errors


def create_aws_clients(profile: str | None, region: str):
    try:
        import boto3
        from botocore.config import Config
    except ImportError as error:
        raise RuntimeError(
            "boto3 is required; install requirements-aws.txt"
        ) from error
    session = boto3.Session(profile_name=profile, region_name=region)
    retry = {"max_attempts": 10, "mode": "adaptive"}
    config = Config(region_name=region, signature_version="s3v4", retries=retry)
    return session.client("s3", config=config), session.client("sts", config=config)


def find_s3_object(s3, bucket: str, object_key: str):
    try:
        return s3.head_object(Bucket=bucket, Key=object_key)
    except Exception as error:
        response = getattr(error, "response", {})
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = clean(response.get("Error", {}).get("Code"))
        if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise


def _last_modified(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return ""


def fill_s3_result(row: dict[str, str], info: dict[str, object]) -> None:
    row["s3_etag"] = clean(info.get("ETag")).strip('"')
    row["s3_version_id"] = clean(info.get("VersionId"))
    row["s3_last_modified"] = _last_modified(info.get("LastModified"))


def object_matches(row: dict[str, str], info: dict[str, object]) -> bool:
    metadata = info.get("Metadata") or {}
    return (
        int(info.get("ContentLength") or -1) == int(row["file_size_bytes"])
        and isinstance(metadata, dict)
        and clean(metadata.get("sha256")).lower() == clean(row.get("sha256")).lower()
        and clean(info.get("ContentType")) == "image/png"
    )


def upload_one(row: dict[str, str], *, project_root: Path, s3) -> str:
    bucket = clean(row.get("bucket"))
    object_key = clean(row.get("object_key"))
    existing = find_s3_object(s3, bucket, object_key)
    row["upload_error"] = ""
    if existing is not None:
        fill_s3_result(row, existing)
        if object_matches(row, existing):
            row["upload_status"] = "already_exists"
            return "already_exists"
        row["upload_status"] = "conflict"
        row["upload_error"] = "existing object differs in size, SHA-256, or content type"
        return "conflict"

    local_path = resolve_local_path(project_root, clean(row.get("original_image_path")))
    s3.upload_file(
        str(local_path),
        bucket,
        object_key,
        ExtraArgs={
            "ContentType": "image/png",
            "CacheControl": "public, max-age=86400",
            "Metadata": {
                "sha256": clean(row.get("sha256")),
                "pokedex-number": clean(row.get("pokedex_number")),
                "image-id": clean(row.get("image_id")),
            },
        },
    )
    uploaded = s3.head_object(Bucket=bucket, Key=object_key)
    if not object_matches(row, uploaded):
        raise RuntimeError("uploaded object metadata validation failed")
    fill_s3_result(row, uploaded)
    row["upload_status"] = "uploaded"
    row["uploaded_at"] = utc_now()
    return "uploaded"


def verify_s3_rows(rows: list[dict[str, str]], s3, workers: int) -> list[str]:
    candidates = [row for row in rows if clean(row.get("upload_status")) in SUCCESS_STATUSES]

    def inspect(row: dict[str, str]):
        info = s3.head_object(Bucket=clean(row.get("bucket")), Key=clean(row.get("object_key")))
        return row, info

    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_rows = {executor.submit(inspect, row): row for row in candidates}
        for future in as_completed(future_rows):
            row = future_rows[future]
            try:
                row, info = future.result()
                fill_s3_result(row, info)
                if not object_matches(row, info):
                    raise RuntimeError("size, SHA-256 metadata, or content type mismatch")
                row["s3_validation_status"] = "verified"
                row["s3_verified_at"] = utc_now()
                row["s3_error"] = ""
            except Exception as error:
                row["s3_validation_status"] = "failed"
                row["s3_error"] = f"{type(error).__name__}: {error}"
                errors.append(f"{row['image_id']}: {row['s3_error']}")
    return errors


def fetch_delivery(url: str, timeout: float) -> tuple[bytes, str]:
    request = Request(
        url,
        headers={"User-Agent": "PokemonPersonalityMVP/1.0", "Cache-Control": "no-cache"},
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read(), clean(response.headers.get("Content-Type")).split(";", 1)[0]


def verify_delivery_rows(
    rows: list[dict[str, str]],
    *,
    workers: int,
    timeout: float,
    fetcher: Callable[[str, float], tuple[bytes, str]] = fetch_delivery,
) -> list[str]:
    candidates = [
        row
        for row in rows
        if clean(row.get("upload_status")) in SUCCESS_STATUSES
        and clean(row.get("s3_validation_status")) == "verified"
    ]

    def inspect(row: dict[str, str]):
        data, content_type = fetcher(clean(row.get("delivery_url")), timeout)
        if content_type != "image/png":
            raise RuntimeError(f"unexpected content type {content_type!r}")
        if len(data) != int(row["file_size_bytes"]):
            raise RuntimeError("content length mismatch")
        if hashlib.sha256(data).hexdigest() != clean(row.get("sha256")).lower():
            raise RuntimeError("SHA-256 mismatch")
        return row

    errors: list[str] = []
    future_rows = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for row in candidates:
            future_rows[executor.submit(inspect, row)] = row
        for future in as_completed(future_rows):
            row = future_rows[future]
            try:
                future.result()
                row["delivery_validation_status"] = "verified"
                row["delivery_verified_at"] = utc_now()
                row["delivery_error"] = ""
            except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as error:
                row["delivery_validation_status"] = "failed"
                row["delivery_error"] = f"{type(error).__name__}: {error}"
                errors.append(f"{row['image_id']}: {row['delivery_error']}")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--delivery-base-url", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--required-prefix", default="images/pokemon/artwork/")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--checkpoint-every", type=int, default=50)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--verify-delivery", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser


def run(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.resolve()
    output_path = args.output.resolve()
    project_root = args.project_root.resolve()
    if manifest_path == output_path:
        raise ValueError("output must not overwrite the source manifest")
    if args.limit is not None and args.limit <= 0:
        raise ValueError("limit must be greater than zero")
    if args.workers <= 0 or args.timeout <= 0 or args.checkpoint_every <= 0:
        raise ValueError("workers, timeout, and checkpoint-every must be positive")
    if args.resume and not output_path.is_file():
        raise ValueError("resume requested but result CSV does not exist")
    if args.execute and not args.resume and output_path.exists():
        raise ValueError("result CSV exists; use --resume instead of overwriting it")

    input_path = output_path if args.resume else manifest_path
    rows, source_fields = read_csv(input_path)
    fields = add_result_columns(source_fields)
    errors = validate_manifest(
        rows,
        project_root=project_root,
        bucket=args.bucket,
        region=args.region,
        required_prefix=args.required_prefix,
        delivery_base_url=args.delivery_base_url,
    )
    if errors:
        print(f"Manifest 驗證失敗：{len(errors)} 項")
        for error in errors[:30]:
            print(f"  - {error}")
        return 2

    pending = [
        index
        for index, row in enumerate(rows)
        if clean(row.get("upload_status")) not in SUCCESS_STATUSES
    ]
    if args.limit is not None:
        pending = pending[: args.limit]
    total_bytes = sum(int(rows[index]["file_size_bytes"]) for index in pending)
    print(f"本機驗證：{len(rows)} 筆 ready")
    print(f"待處理：{len(pending)} 筆，{total_bytes / (1024 ** 2):.2f} MiB")
    print(f"結果：{output_path}")
    if not args.execute:
        print("Dry run 完成；沒有連線或修改 AWS。")
        return 0

    s3, sts = create_aws_clients(args.profile, args.region)
    identity = sts.get_caller_identity()
    s3.head_bucket(Bucket=args.bucket)
    print(f"AWS Account：{identity.get('Account', '')}")
    print(f"AWS ARN：{identity.get('Arn', '')}")
    print(f"Bucket：{args.bucket}")

    counters: Counter[str] = Counter()
    for position, index in enumerate(pending, start=1):
        row = rows[index]
        try:
            status = upload_one(row, project_root=project_root, s3=s3)
        except KeyboardInterrupt:
            write_csv_safely(output_path, rows, fields)
            return 130
        except Exception as error:
            status = "failed"
            row["upload_status"] = status
            row["upload_error"] = f"{type(error).__name__}: {error}"
        counters[status] += 1
        if position % args.checkpoint_every == 0 or position == len(pending):
            write_csv_safely(output_path, rows, fields)
            print(
                f"上傳進度：{position}/{len(pending)} "
                f"(失敗 {counters['failed']}、衝突 {counters['conflict']})",
                flush=True,
            )

    s3_errors = verify_s3_rows(rows, s3, args.workers)
    delivery_errors: list[str] = []
    if args.verify_delivery:
        delivery_errors = verify_delivery_rows(
            rows, workers=args.workers, timeout=args.timeout
        )
    write_csv_safely(output_path, rows, fields)

    unresolved = [
        rows[index]
        for index in pending
        if clean(rows[index].get("upload_status")) not in SUCCESS_STATUSES
    ]
    remaining = sum(
        clean(row.get("upload_status")) not in SUCCESS_STATUSES for row in rows
    )
    print(f"S3 已驗證：{sum(row.get('s3_validation_status') == 'verified' for row in rows)}")
    if args.verify_delivery:
        print(
            "CloudFront 已驗證："
            f"{sum(row.get('delivery_validation_status') == 'verified' for row in rows)}"
        )
    if unresolved or s3_errors or delivery_errors:
        print(
            f"尚未完成：{len(unresolved)}；S3 錯誤：{len(s3_errors)}；"
            f"CloudFront 錯誤：{len(delivery_errors)}"
        )
        return 4
    if remaining:
        print(f"本次範圍完成；另有 {remaining} 筆可使用 --resume 繼續。")
        return 0
    print("全部圖片與網址驗證完成。")
    return 0


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except Exception as error:
        print(f"錯誤：{error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
