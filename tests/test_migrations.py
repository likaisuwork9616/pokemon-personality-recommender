import unittest
from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db import Base


ROOT = Path(__file__).resolve().parents[1]
CORE_TABLES = {
    "pokemon",
    "types",
    "pokemon_types",
    "pokemon_stats",
    "pokemon_descriptions",
    "pokemon_images",
}
KNOWLEDGE_TABLES = {
    "pokemon_knowledge_documents",
    "pokemon_knowledge_chunks",
}


class CoreSchemaTests(unittest.TestCase):
    def test_metadata_contains_the_core_chapter_tables(self):
        self.assertTrue(CORE_TABLES.issubset(Base.metadata.tables))

    def test_pokemon_identity_and_form_key_are_constrained(self):
        table = Base.metadata.tables["pokemon"]
        uniques = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }

        self.assertEqual(table.primary_key.name, "pk_pokemon")
        self.assertEqual(table.c.id.identity.always, True)
        self.assertIn(("pokedex_number", "form_key"), uniques)
        self.assertFalse(table.c.generation.nullable)
        self.assertFalse(table.c.is_active.nullable)

    def test_type_slots_and_foreign_key_delete_rules_are_explicit(self):
        table = Base.metadata.tables["pokemon_types"]
        delete_rules = {
            foreign_key.parent.name: foreign_key.ondelete
            for foreign_key in table.foreign_keys
        }
        checks = " ".join(
            str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        )

        self.assertEqual(delete_rules, {"pokemon_id": "CASCADE", "type_id": "RESTRICT"})
        self.assertIn("slot IN (1, 2)", checks)

    def test_stats_cover_raw_and_scaled_csv_features(self):
        table = Base.metadata.tables["pokemon_stats"]
        expected = {
            "pokemon_id",
            "hp",
            "attack",
            "defense",
            "sp_attack",
            "sp_defense",
            "speed",
            "base_stat_total",
            "scaled_hp",
            "scaled_attack",
            "scaled_defense",
            "scaled_sp_attack",
            "scaled_sp_defense",
            "scaled_speed",
            "scaled_height_m",
            "scaled_weight_kg",
        }
        checks = " ".join(
            str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        )

        self.assertEqual(set(table.c.keys()), expected)
        self.assertIn("base_stat_total = hp + attack", checks)

    def test_description_and_image_source_rows_are_idempotent(self):
        descriptions = Base.metadata.tables["pokemon_descriptions"]
        images = Base.metadata.tables["pokemon_images"]
        description_uniques = {
            tuple(column.name for column in constraint.columns)
            for constraint in descriptions.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        image_uniques = {
            tuple(column.name for column in constraint.columns)
            for constraint in images.constraints
            if isinstance(constraint, UniqueConstraint)
        }

        self.assertIn(
            ("pokemon_id", "language_code", "description_kind", "source_key"),
            description_uniques,
        )
        self.assertIn(("pokemon_id", "image_kind"), image_uniques)

    def test_models_compile_for_postgresql(self):
        ddl = "\n".join(
            str(CreateTable(table).compile(dialect=postgresql.dialect()))
            for table in Base.metadata.sorted_tables
        )

        self.assertIn("GENERATED ALWAYS AS IDENTITY", ddl)
        self.assertIn("FOREIGN KEY(pokemon_id) REFERENCES pokemon (id) ON DELETE CASCADE", ddl)
        self.assertIn("DOUBLE PRECISION", ddl)

    def test_initial_revision_installs_vector_without_vector_columns(self):
        revision = (
            ROOT / "alembic" / "versions" / "20260906_0001_core_schema.py"
        ).read_text(encoding="utf-8")

        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", revision)
        self.assertIn("DROP EXTENSION IF EXISTS vector", revision)
        self.assertNotIn("Vector(", revision)
        self.assertNotIn("knowledge_chunks", revision)

    def test_second_revision_adds_versioned_uuid_documents_and_fts_chunks(self):
        self.assertTrue(KNOWLEDGE_TABLES.issubset(Base.metadata.tables))
        chunks = Base.metadata.tables["pokemon_knowledge_chunks"]
        self.assertIsNotNone(chunks.c.textsearch.computed)
        revision = (
            ROOT / "alembic" / "versions" / "20260906_0002_knowledge_documents.py"
        ).read_text(encoding="utf-8")
        self.assertIn('down_revision: str | None = "20260906_0001"', revision)
        self.assertIn('postgresql_using="gin"', revision)
        self.assertIn("to_tsvector('simple'", revision)


if __name__ == "__main__":
    unittest.main()
