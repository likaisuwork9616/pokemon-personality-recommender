from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import audit_artwork_delivery as audit


PNG = b"\x89PNG\r\n\x1a\nfixture"


class ArtworkAuditTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        digest = hashlib.sha256(PNG).hexdigest()
        source_rows: list[dict[str, str]] = []
        delivery_rows: list[dict[str, str]] = []
        for number in (1, 2):
            filename = f"{number:04d}_寶可夢{number}.png"
            (root / filename).write_bytes(PNG)
            source_rows.append(
                {
                    "pokedex_number": str(number),
                    "filename": filename,
                    "source_url": (
                        "https://tw.portal-pokemon.com/images/pokedex/"
                        f"{number:04d}.png"
                    ),
                    "sha256": digest,
                    "status": "downloaded",
                }
            )
            delivery_rows.append(
                {
                    "pokedex_number": str(number),
                    "delivery_url": (
                        "https://cdn.example.cloudfront.net/"
                        f"images/pokemon/artwork/{number:04d}.png"
                    ),
                    "sha256": digest,
                    "s3_validation_status": "verified",
                    "delivery_validation_status": "verified",
                }
            )
        return source_rows, delivery_rows

    def test_local_audit_requires_official_lineage_and_verified_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_rows, delivery_rows = self.fixture(root)
            with patch.object(audit, "EXPECTED_POKEMON_COUNT", 2):
                summary, errors = audit.audit_local_records(
                    source_rows,
                    delivery_rows,
                    images_dir=root,
                )

        self.assertEqual(errors, [])
        self.assertEqual(summary["local_png_sha256_verified"], 2)
        self.assertEqual(summary["delivery_records_verified"], 2)

    def test_local_audit_rejects_unexpected_source_host(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_rows, delivery_rows = self.fixture(root)
            source_rows[0]["source_url"] = "https://untrusted.example/0001.png"
            with patch.object(audit, "EXPECTED_POKEMON_COUNT", 2):
                _summary, errors = audit.audit_local_records(
                    source_rows,
                    delivery_rows,
                    images_dir=root,
                )

        self.assertTrue(any("unexpected source host" in item for item in errors))

    def test_live_sample_requires_png_and_matching_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            _source_rows, delivery_rows = self.fixture(Path(directory))
            verified, errors = audit.sample_delivery_rows(
                delivery_rows,
                sample_size=2,
                timeout=1,
                fetcher=lambda _url, _timeout: (PNG, "image/png"),
            )

        self.assertEqual(verified, [1, 2])
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
