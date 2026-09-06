from __future__ import annotations

import csv
import hashlib
import os
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.db.models import (
    Pokemon,
    PokemonDescription,
    PokemonImage,
    PokemonKnowledgeChunk,
    PokemonKnowledgeDocument,
    PokemonStats,
    PokemonType,
    Type,
)
from app.services.csv_importer import (
    CSV_COLUMNS,
    DEFAULT_CSV_PATH,
    CsvImportError,
    CsvPokemonImporter,
    parse_csv_row,
    read_csv_records,
)


def raw_rows() -> list[dict[str, str]]:
    with DEFAULT_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class CsvParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = raw_rows()

    def test_full_dataset_is_strictly_parsed(self):
        records = read_csv_records(DEFAULT_CSV_PATH)

        self.assertEqual(len(records), 1025)
        self.assertEqual(records[0].pokemon.pokedex_number, 1)
        self.assertEqual(records[-1].pokemon.pokedex_number, 1025)
        self.assertEqual(len({record.pokemon.pokedex_number for record in records}), 1025)

    def test_row_maps_every_relational_child(self):
        record = parse_csv_row(self.rows[0], row_number=2)

        self.assertEqual(record.pokemon.name_zh, "妙蛙種子")
        self.assertEqual(record.pokemon.generation, 1)
        self.assertEqual(record.type_codes, ("grass", "poison"))
        self.assertEqual(record.stats.base_stat_total, 318)
        self.assertEqual(
            [item.source_key for item in record.descriptions],
            ["csv:description_zh", "csv:flavor_text_en", "csv:analysis_text"],
        )
        self.assertTrue(all(len(item.content_hash) == 64 for item in record.descriptions))
        self.assertEqual(
            [(item.image_kind, item.is_primary) for item in record.images],
            [("artwork", True), ("sprite", False)],
        )

    def test_unknown_sentinels_and_type_null_are_normalized(self):
        type_null = next(row for row in self.rows if row["pokedex_number"] == "772")
        record = parse_csv_row(type_null, row_number=773)

        self.assertEqual(record.type_codes, ("normal",))
        self.assertIsNone(record.pokemon.hidden_ability)
        self.assertIsNone(record.pokemon.habitat)

    def test_invalid_boolean_generation_number_and_stat_total_are_rejected(self):
        cases = (
            ("is_legendary", "yes"),
            ("generation", "generation-one"),
            ("height_m", "NaN"),
            ("base_stat_total", "999"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                row = dict(self.rows[0])
                row[field] = value
                with self.assertRaisesRegex(CsvImportError, field):
                    parse_csv_row(row, row_number=2)

    def test_type_translation_must_match_english_slots(self):
        row = dict(self.rows[0])
        row["type_zh"] = "火"

        with self.assertRaisesRegex(CsvImportError, "type_zh"):
            parse_csv_row(row, row_number=2)

    def test_header_rejects_missing_or_unmapped_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.csv"
            fieldnames = [column for column in CSV_COLUMNS if column != "name_zh"]
            fieldnames.append("unmapped")
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()

            with self.assertRaisesRegex(CsvImportError, "header is invalid"):
                read_csv_records(path)


class _FakeTransaction:
    def __init__(self) -> None:
        self.is_active = True
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True
        self.is_active = False

    def rollback(self) -> None:
        self.rolled_back = True
        self.is_active = False


class _FakeSession:
    def __init__(self) -> None:
        self.transaction = _FakeTransaction()
        self.closed = False

    def begin(self) -> _FakeTransaction:
        return self.transaction

    def close(self) -> None:
        self.closed = True


class _FakeRepository:
    def __init__(self, _session: _FakeSession) -> None:
        self.records = []

    def seed_types(self, definitions):
        return {code: index for index, code in enumerate(definitions, start=1)}

    def get_by_natural_key(self, _pokedex_number, _form_key):
        return None

    def upsert_record(self, record, _type_ids):
        self.records.append(record)


class ImportTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.record = parse_csv_row(raw_rows()[0], row_number=2)

    def test_dry_run_rolls_back_and_closes_session(self):
        session = _FakeSession()
        importer = CsvPokemonImporter(
            lambda: session,
            repository_factory=_FakeRepository,
        )

        summary = importer.import_records([self.record], dry_run=True)

        self.assertTrue(summary.dry_run)
        self.assertEqual(summary.created, 1)
        self.assertTrue(session.transaction.rolled_back)
        self.assertFalse(session.transaction.committed)
        self.assertTrue(session.closed)


@unittest.skipUnless(
    os.getenv("TEST_DATABASE_URL"),
    "Set TEST_DATABASE_URL to a disposable PostgreSQL database to run integration tests",
)
class PostgresImporterIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        database_url = os.environ["TEST_DATABASE_URL"]
        self.admin_engine = create_engine(database_url)
        self.schema = f"test_csv_importer_{uuid.uuid4().hex}"
        with self.admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_engine(
            database_url,
            connect_args={"options": f"-csearch_path={self.schema}"},
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )
        self.records = read_csv_records(DEFAULT_CSV_PATH)[:2]

    def tearDown(self) -> None:
        self.engine.dispose()
        with self.admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.admin_engine.dispose()

    def scalar_count(self, model) -> int:
        with self.session_factory() as session:
            return int(session.scalar(select(func.count()).select_from(model)) or 0)

    def test_upsert_is_idempotent_preserves_active_and_supports_dry_run(self):
        importer = CsvPokemonImporter(self.session_factory)
        first = importer.import_records(self.records)
        self.assertEqual((first.created, first.existing), (2, 0))
        self.assertEqual(self.scalar_count(Pokemon), 2)
        self.assertEqual(self.scalar_count(Type), 18)
        self.assertEqual(self.scalar_count(PokemonType), 4)
        self.assertEqual(self.scalar_count(PokemonStats), 2)
        self.assertEqual(self.scalar_count(PokemonDescription), 6)
        self.assertEqual(self.scalar_count(PokemonImage), 4)
        self.assertEqual(self.scalar_count(PokemonKnowledgeDocument), 8)
        first_chunk_count = self.scalar_count(PokemonKnowledgeChunk)
        self.assertGreaterEqual(first_chunk_count, 8)

        with self.session_factory() as session:
            before = list(
                session.execute(
                    select(Pokemon.id, Pokemon.updated_at).order_by(Pokemon.id)
                )
            )
        second = importer.import_records(self.records)
        self.assertEqual((second.created, second.existing), (0, 2))
        self.assertEqual(self.scalar_count(PokemonKnowledgeDocument), 8)
        self.assertEqual(self.scalar_count(PokemonKnowledgeChunk), first_chunk_count)
        with self.session_factory() as session:
            after = list(
                session.execute(
                    select(Pokemon.id, Pokemon.updated_at).order_by(Pokemon.id)
                )
            )
        self.assertEqual(before, after)

        with self.session_factory.begin() as session:
            pokemon = session.scalar(
                select(Pokemon).where(Pokemon.pokedex_number == 1)
            )
            pokemon.is_active = False
        importer.import_records(self.records)
        with self.session_factory() as session:
            self.assertFalse(
                session.scalar(
                    select(Pokemon.is_active).where(Pokemon.pokedex_number == 1)
                )
            )

        changed_payload = replace(self.records[0].pokemon, name_zh="測試名稱")
        changed_record = replace(self.records[0], pokemon=changed_payload)
        importer.import_records([changed_record], dry_run=True)
        with self.session_factory() as session:
            self.assertEqual(
                session.scalar(
                    select(Pokemon.name_zh).where(Pokemon.pokedex_number == 1)
                ),
                self.records[0].pokemon.name_zh,
            )

        changed_content = "更新後的可追蹤內容"
        changed_description = replace(
            self.records[0].descriptions[0],
            content=changed_content,
            content_hash=hashlib.sha256(changed_content.encode("utf-8")).hexdigest(),
        )
        changed_record = replace(
            self.records[0],
            descriptions=(changed_description, *self.records[0].descriptions[1:]),
        )
        importer.import_records([changed_record])
        with self.session_factory() as session:
            stored = session.scalar(
                select(PokemonDescription).where(
                    PokemonDescription.pokemon_id
                    == select(Pokemon.id)
                    .where(Pokemon.pokedex_number == 1)
                    .scalar_subquery(),
                    PokemonDescription.source_key == "csv:description_zh",
                )
            )
            self.assertEqual(stored.content, changed_content)
            versions = list(
                session.scalars(
                    select(PokemonKnowledgeDocument.version)
                    .where(
                        PokemonKnowledgeDocument.pokemon_id == stored.pokemon_id,
                        PokemonKnowledgeDocument.source_key == "description_zh",
                    )
                    .order_by(PokemonKnowledgeDocument.version)
                )
            )
            self.assertEqual(versions, [1, 2])


if __name__ == "__main__":
    unittest.main()
