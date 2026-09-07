"""Build a validated, auditable S3 upload manifest for Pokemon artwork."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = PROJECT_ROOT / "pokemon_descript" / "pokedex_final.csv"
DEFAULT_IMAGES_DIR = PROJECT_ROOT / "pk_pic"
DEFAULT_SOURCE_MANIFEST = DEFAULT_IMAGES_DIR / "_manifest.csv"
DEFAULT_OUTPUT = DEFAULT_IMAGES_DIR / "manifests" / "pokemon_image_upload_manifest.csv"
EXPECTED_POKEMON_COUNT = 1025
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

MANIFEST_COLUMNS = (
    "manifest_version",
    "image_id",
    "pokedex_number",
    "name_zh",
    "name_en",
    "source",
    "image_role",
    "source_url",
    "original_image_path",
    "local_file_exists",
    "file_size_bytes",
    "width_px",
    "height_px",
    "sha256",
    "upload_filename",
    "bucket",
    "region",
    "object_key",
    "content_type",
    "validation_status",
    "validation_message",
    "upload_status",
    "s3_etag",
    "uploaded_at",
    "s3_uri",
    "s3_https_url",
    "delivery_url",
    "delivery_url_type",
    "s3_version_id",
    "s3_last_modified",
    "s3_validation_status",
    "s3_verified_at",
    "s3_error",
    "upload_error",
    "delivery_validation_status",
    "delivery_verified_at",
    "delivery_error",
)


class ManifestError(ValueError):
    """The local catalog or artwork directory violates the upload contract."""


def clean_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ManifestError(
            "delivery base URL must be absolute HTTP(S) without query or fragment"
        )
    return normalized


def safe_artwork_filename(pokedex_number: int, name_zh: str) -> str:
    safe_name = INVALID_FILENAME_CHARACTERS.sub("_", name_zh).strip(" .")
    if not safe_name:
        raise ManifestError(f"No.{pokedex_number:04d} has no safe filename")
    return f"{pokedex_number:04d}_{safe_name}.png"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ManifestError(f"CSV has no header: {path}")
        return [dict(row) for row in reader]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if (
        len(header) < 24
        or not header.startswith(PNG_SIGNATURE)
        or header[12:16] != b"IHDR"
    ):
        raise ManifestError(f"not a valid PNG header: {path}")
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    if width <= 0 or height <= 0:
        raise ManifestError(f"invalid PNG dimensions: {path}")
    return width, height


def _relative_or_absolute(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _catalog_index(rows: list[dict[str, str]]) -> dict[int, dict[str, str]]:
    required = {"pokedex_number", "name_zh", "name_en"}
    if not rows or not required.issubset(rows[0]):
        raise ManifestError(f"catalog must contain: {', '.join(sorted(required))}")
    result: dict[int, dict[str, str]] = {}
    seen_names: set[str] = set()
    for row in rows:
        number = int((row.get("pokedex_number") or "").strip())
        name_zh = (row.get("name_zh") or "").strip()
        if number in result:
            raise ManifestError(f"duplicate catalog number: {number}")
        if not name_zh or name_zh in seen_names:
            raise ManifestError(f"blank or duplicate catalog name: {name_zh!r}")
        result[number] = row
        seen_names.add(name_zh)
    if set(result) != set(range(1, EXPECTED_POKEMON_COUNT + 1)):
        missing = sorted(set(range(1, EXPECTED_POKEMON_COUNT + 1)) - set(result))
        extra = sorted(set(result) - set(range(1, EXPECTED_POKEMON_COUNT + 1)))
        raise ManifestError(f"catalog identity mismatch; missing={missing}, extra={extra}")
    return result


def _source_index(rows: list[dict[str, str]]) -> dict[int, dict[str, str]]:
    required = {"pokedex_number", "name_zh", "filename", "source_url", "sha256"}
    if not rows or not required.issubset(rows[0]):
        raise ManifestError(
            f"source manifest must contain: {', '.join(sorted(required))}"
        )
    result: dict[int, dict[str, str]] = {}
    for row in rows:
        number = int((row.get("pokedex_number") or "").strip())
        if number in result:
            raise ManifestError(f"duplicate source manifest number: {number}")
        result[number] = row
    if len(result) != EXPECTED_POKEMON_COUNT:
        raise ManifestError(
            f"source manifest must contain {EXPECTED_POKEMON_COUNT} rows, got {len(result)}"
        )
    return result


def build_manifest_rows(
    *,
    project_root: Path,
    catalog_path: Path,
    images_dir: Path,
    source_manifest_path: Path,
    bucket: str,
    region: str,
    delivery_base_url: str,
    object_prefix: str = "images/pokemon/artwork/",
) -> list[dict[str, str]]:
    bucket = bucket.strip()
    region = region.strip()
    prefix = object_prefix.strip().strip("/") + "/"
    delivery_base = clean_base_url(delivery_base_url)
    if not bucket or not region:
        raise ManifestError("bucket and region are required")

    catalog = _catalog_index(read_csv(catalog_path))
    sources = _source_index(read_csv(source_manifest_path))
    actual_png_names = {path.name for path in images_dir.glob("*.png") if path.is_file()}
    expected_png_names: set[str] = set()
    rows: list[dict[str, str]] = []

    for number in range(1, EXPECTED_POKEMON_COUNT + 1):
        catalog_row = catalog[number]
        source_row = sources.get(number)
        if source_row is None:
            raise ManifestError(f"source manifest is missing No.{number:04d}")
        name_zh = (catalog_row.get("name_zh") or "").strip()
        expected_filename = safe_artwork_filename(number, name_zh)
        expected_png_names.add(expected_filename)
        if (source_row.get("name_zh") or "").strip() != name_zh:
            raise ManifestError(f"name mismatch at No.{number:04d}")
        if (source_row.get("filename") or "").strip() != expected_filename:
            raise ManifestError(f"filename mismatch at No.{number:04d}")

        local_path = images_dir / expected_filename
        if not local_path.is_file():
            raise ManifestError(f"missing local image: {local_path}")
        width, height = read_png_dimensions(local_path)
        file_hash = sha256_file(local_path)
        recorded_hash = (source_row.get("sha256") or "").strip().lower()
        if recorded_hash and recorded_hash != file_hash:
            raise ManifestError(f"source SHA-256 mismatch at No.{number:04d}")

        object_key = f"{prefix}{number:04d}.png"
        encoded_key = quote(object_key, safe="/")
        rows.append(
            {
                "manifest_version": "1.0",
                "image_id": f"pokemon-{number:04d}-artwork",
                "pokedex_number": str(number),
                "name_zh": name_zh,
                "name_en": (catalog_row.get("name_en") or "").strip(),
                "source": "pokemon_official_tw",
                "image_role": "artwork",
                "source_url": (source_row.get("source_url") or "").strip(),
                "original_image_path": _relative_or_absolute(local_path, project_root),
                "local_file_exists": "true",
                "file_size_bytes": str(local_path.stat().st_size),
                "width_px": str(width),
                "height_px": str(height),
                "sha256": file_hash,
                "upload_filename": f"{number:04d}.png",
                "bucket": bucket,
                "region": region,
                "object_key": object_key,
                "content_type": "image/png",
                "validation_status": "ready",
                "validation_message": "",
                "upload_status": "pending",
                "s3_etag": "",
                "uploaded_at": "",
                "s3_uri": f"s3://{bucket}/{object_key}",
                "s3_https_url": f"https://{bucket}.s3.{region}.amazonaws.com/{encoded_key}",
                "delivery_url": f"{delivery_base}/{encoded_key}",
                "delivery_url_type": "cloudfront",
                "s3_version_id": "",
                "s3_last_modified": "",
                "s3_validation_status": "pending",
                "s3_verified_at": "",
                "s3_error": "",
                "upload_error": "",
                "delivery_validation_status": "pending",
                "delivery_verified_at": "",
                "delivery_error": "",
            }
        )

    extras = sorted(actual_png_names - expected_png_names)
    missing = sorted(expected_png_names - actual_png_names)
    if extras or missing:
        raise ManifestError(f"image directory mismatch; missing={missing}, extra={extras}")
    if len({row["object_key"] for row in rows}) != EXPECTED_POKEMON_COUNT:
        raise ManifestError("object keys are not unique")
    return rows


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES_DIR)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--delivery-base-url", required=True)
    parser.add_argument("--object-prefix", default="images/pokemon/artwork/")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        rows = build_manifest_rows(
            project_root=args.project_root.resolve(),
            catalog_path=args.catalog.resolve(),
            images_dir=args.images_dir.resolve(),
            source_manifest_path=args.source_manifest.resolve(),
            bucket=args.bucket,
            region=args.region,
            delivery_base_url=args.delivery_base_url,
            object_prefix=args.object_prefix,
        )
        write_manifest(args.output.resolve(), rows)
    except (OSError, ManifestError, ValueError) as error:
        print(f"錯誤：{error}")
        return 2
    print(
        json.dumps(
            {
                "manifest": str(args.output.resolve()),
                "rows": len(rows),
                "ready": sum(row["validation_status"] == "ready" for row in rows),
                "total_bytes": sum(int(row["file_size_bytes"]) for row in rows),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
