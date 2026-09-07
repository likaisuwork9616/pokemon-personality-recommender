from __future__ import annotations

import argparse
import csv
import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import build_pokemon_image_manifest as builder
from scripts import pokemon_s3_image_uploader as uploader


MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x02\x00\x00\x00\x03"
    b"\x08\x06\x00\x00\x00"
)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class ManifestBuilderTests(unittest.TestCase):
    def create_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        images = root / "pk_pic"
        images.mkdir()
        catalog = root / "catalog.csv"
        source = images / "_manifest.csv"
        catalog_rows = [
            {"pokedex_number": "1", "name_zh": "妙蛙種子", "name_en": "Bulbasaur"},
            {"pokedex_number": "2", "name_zh": "妙蛙草", "name_en": "Ivysaur"},
        ]
        source_rows: list[dict[str, str]] = []
        digest = hashlib.sha256(MINIMAL_PNG).hexdigest()
        for row in catalog_rows:
            number = int(row["pokedex_number"])
            filename = builder.safe_artwork_filename(number, row["name_zh"])
            (images / filename).write_bytes(MINIMAL_PNG)
            source_rows.append(
                {
                    "pokedex_number": str(number),
                    "name_zh": row["name_zh"],
                    "filename": filename,
                    "source_url": f"https://official.example/{number}.png",
                    "sha256": digest,
                }
            )
        write_csv(catalog, catalog_rows)
        write_csv(source, source_rows)
        return catalog, images, source

    def build(self, root: Path) -> list[dict[str, str]]:
        catalog, images, source = self.create_fixture(root)
        with patch.object(builder, "EXPECTED_POKEMON_COUNT", 2):
            return builder.build_manifest_rows(
                project_root=root,
                catalog_path=catalog,
                images_dir=images,
                source_manifest_path=source,
                bucket="pokemon-test",
                region="ap-east-2",
                delivery_base_url="https://cdn.example.test",
            )

    def test_builds_traceable_numeric_object_keys_and_recomputes_png_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = self.build(Path(directory))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["object_key"], "images/pokemon/artwork/0001.png")
        self.assertEqual(rows[0]["name_zh"], "妙蛙種子")
        self.assertEqual((rows[0]["width_px"], rows[0]["height_px"]), ("2", "3"))
        self.assertEqual(
            rows[0]["delivery_url"],
            "https://cdn.example.test/images/pokemon/artwork/0001.png",
        )
        self.assertEqual(rows[0]["validation_status"], "ready")

    def test_rejects_source_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog, images, source = self.create_fixture(root)
            rows = builder.read_csv(source)
            rows[0]["sha256"] = "0" * 64
            write_csv(source, rows)

            with patch.object(builder, "EXPECTED_POKEMON_COUNT", 2):
                with self.assertRaisesRegex(builder.ManifestError, "SHA-256 mismatch"):
                    builder.build_manifest_rows(
                        project_root=root,
                        catalog_path=catalog,
                        images_dir=images,
                        source_manifest_path=source,
                        bucket="pokemon-test",
                        region="ap-east-2",
                        delivery_base_url="https://cdn.example.test",
                    )


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, object]] = {}
        self.uploads = 0

    def head_object(self, *, Bucket: str, Key: str):
        try:
            return self.objects[(Bucket, Key)]
        except KeyError as error:
            class NotFoundError(Exception):
                response = {
                    "Error": {"Code": "404", "Message": "Not Found"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                }

            raise NotFoundError("not found") from error

    def upload_file(self, filename, bucket, key, ExtraArgs):
        self.uploads += 1
        self.objects[(bucket, key)] = {
            "ContentLength": Path(filename).stat().st_size,
            "ContentType": ExtraArgs["ContentType"],
            "Metadata": ExtraArgs["Metadata"],
            "ETag": '"etag"',
            "LastModified": datetime.now(timezone.utc),
        }


class UploaderTests(unittest.TestCase):
    def make_row(self, root: Path) -> dict[str, str]:
        image = root / "image.png"
        image.write_bytes(MINIMAL_PNG)
        digest = hashlib.sha256(MINIMAL_PNG).hexdigest()
        return {
            "image_id": "pokemon-0001-artwork",
            "pokedex_number": "1",
            "name_zh": "妙蛙種子",
            "source": "pokemon_official_tw",
            "image_role": "artwork",
            "original_image_path": "image.png",
            "file_size_bytes": str(len(MINIMAL_PNG)),
            "sha256": digest,
            "bucket": "pokemon-test",
            "region": "ap-east-2",
            "object_key": "images/pokemon/artwork/0001.png",
            "content_type": "image/png",
            "validation_status": "ready",
            "upload_status": "pending",
            "s3_uri": "s3://pokemon-test/images/pokemon/artwork/0001.png",
            "s3_https_url": "https://pokemon-test.s3.ap-east-2.amazonaws.com/images/pokemon/artwork/0001.png",
            "delivery_url": "https://cdn.example.test/images/pokemon/artwork/0001.png",
            "s3_etag": "",
            "uploaded_at": "",
            "s3_version_id": "",
            "s3_last_modified": "",
            "upload_error": "",
            "s3_validation_status": "pending",
            "s3_verified_at": "",
            "s3_error": "",
            "delivery_validation_status": "pending",
            "delivery_verified_at": "",
            "delivery_error": "",
        }

    def test_upload_is_idempotent_by_size_sha_metadata_and_content_type(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = self.make_row(root)
            s3 = FakeS3()

            first = uploader.upload_one(row, project_root=root, s3=s3)
            second = uploader.upload_one(row, project_root=root, s3=s3)

        self.assertEqual(first, "uploaded")
        self.assertEqual(second, "already_exists")
        self.assertEqual(s3.uploads, 1)

    def test_existing_object_with_different_sha_is_a_non_overwriting_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = self.make_row(root)
            s3 = FakeS3()
            s3.objects[(row["bucket"], row["object_key"])] = {
                "ContentLength": len(MINIMAL_PNG),
                "ContentType": "image/png",
                "Metadata": {"sha256": "0" * 64},
            }

            status = uploader.upload_one(row, project_root=root, s3=s3)

        self.assertEqual(status, "conflict")
        self.assertEqual(s3.uploads, 0)

    def test_delivery_verification_requires_png_size_and_sha(self):
        with tempfile.TemporaryDirectory() as directory:
            row = self.make_row(Path(directory))
            row["upload_status"] = "uploaded"
            row["s3_validation_status"] = "verified"
            errors = uploader.verify_delivery_rows(
                [row],
                workers=1,
                timeout=1,
                fetcher=lambda _url, _timeout: (MINIMAL_PNG, "image/png"),
            )

        self.assertEqual(errors, [])
        self.assertEqual(row["delivery_validation_status"], "verified")

    def test_dry_run_never_creates_an_aws_client(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = self.make_row(root)
            manifest = root / "manifest.csv"
            output = root / "result.csv"
            write_csv(manifest, [row])
            args = argparse.Namespace(
                manifest=manifest,
                output=output,
                project_root=root,
                bucket="pokemon-test",
                region="ap-east-2",
                delivery_base_url="https://cdn.example.test",
                profile="pokemon-s3-uploader",
                required_prefix="images/pokemon/artwork/",
                limit=None,
                checkpoint_every=50,
                workers=1,
                timeout=1,
                resume=False,
                verify_delivery=False,
                execute=False,
            )
            with patch.object(uploader, "EXPECTED_POKEMON_COUNT", 1), patch.object(
                uploader, "create_aws_clients"
            ) as create_clients:
                result = uploader.run(args)

        self.assertEqual(result, 0)
        create_clients.assert_not_called()
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
