from __future__ import annotations

import unittest
from uuid import uuid4

import numpy as np
from sqlalchemy.dialects import postgresql

from app.repositories.mbti_profiles import MbtiProfileRepository


class _Session:
    def __init__(self, rows):
        self.rows, self.statements = rows, []

    def execute(self, statement):
        self.statements.append(statement)
        return self.rows


class MbtiProfileRepositoryTests(unittest.TestCase):
    def test_metadata_excludes_editable_descriptions_and_orders_dual_types(self):
        session = _Session([
            (1, 1, "default", "妙蛙種子", "Bulbasaur", "種子", "Seed", 1, "草", "Grass", "artwork", "https://example.test/art.png"),
            (1, 1, "default", "妙蛙種子", "Bulbasaur", "種子", "Seed", 1, "草", "Grass", "sprite", "https://example.test/sprite.png"),
            (1, 1, "default", "妙蛙種子", "Bulbasaur", "種子", "Seed", 2, "毒", "Poison", "artwork", "https://example.test/art.png"),
        ])
        records = MbtiProfileRepository(session).metadata_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["type_zh"], "草, 毒")
        self.assertEqual(records[0]["type_2"], "Poison")
        self.assertEqual(records[0]["sprite_url"], "https://example.test/sprite.png")
        sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
        self.assertTrue(session.statements[0].is_select)
        self.assertNotIn("pokemon_descriptions", sql)
        self.assertNotIn("personality_traits", sql)

    def test_one_read_only_query_loads_full_documents_once_and_averages_chunks(self):
        document_id = uuid4()
        rows = [
            (1, document_id, "完整資料包含合作與可靠", "analysis_text", "analysis", "zh-Hant",
             uuid4(), "第一段合作", "a" * 64, np.eye(2, 384)[0]),
            (1, document_id, "完整資料包含合作與可靠", "analysis_text", "analysis", "zh-Hant",
             uuid4(), "第二段可靠", "b" * 64, np.eye(2, 384)[1]),
        ]
        session = _Session(rows)
        profiles = MbtiProfileRepository(session).load_profiles([1, 1], embedding_model_id=9)
        self.assertEqual(len(session.statements), 1)
        self.assertEqual(profiles[1].text, "完整資料包含合作與可靠")
        self.assertEqual(len(profiles[1].chunks), 2)
        self.assertAlmostEqual(profiles[1].embedding[0], 1 / np.sqrt(2))
        statement = session.statements[0]
        self.assertTrue(statement.is_select)
        sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertNotIn("pokemon_descriptions", sql)
        for expected in (
            "pokemon_chunk_embeddings.content_hash = pokemon_knowledge_chunks.content_hash",
            "embedding_models.dimensions = 384", "embedding_models.is_active IS true",
            "pokemon_knowledge_chunks.is_current IS true", "pokemon_knowledge_documents.is_current IS true",
            "pokemon_chunk_embeddings.status = 'ready'", "pokemon_knowledge_documents.status = 'ready'",
            "pokemon_knowledge_chunks.status = 'ready'", "pokemon_chunk_embeddings.embedding_model_id = 9",
        ):
            self.assertIn(expected, sql)

    def test_empty_input_has_no_database_access_and_limit_is_bounded(self):
        session = _Session([])
        repository = MbtiProfileRepository(session)
        self.assertEqual(repository.load_profiles([], embedding_model_id=9), {})
        self.assertEqual(session.statements, [])
        with self.assertRaises(ValueError):
            repository.load_profiles(list(range(1, 102)), embedding_model_id=9)

    def test_invalid_persisted_embedding_is_rejected_without_writes(self):
        session = _Session([(1, uuid4(), "內容", "analysis_text", "analysis", "zh-Hant",
                             uuid4(), "內容", "a" * 64, [float("nan")] * 384)])
        with self.assertRaises(ValueError):
            MbtiProfileRepository(session).load_profiles([1], embedding_model_id=9)


if __name__ == "__main__":
    unittest.main()
