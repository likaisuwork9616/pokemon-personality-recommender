from __future__ import annotations

import unittest
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.repositories.personality import (
    PERSONALITY_DIMENSIONS,
    PersonalityRepository,
)


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Session:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((statement, params))
        return _Rows(self.results.pop(0))


class PersonalityRepositoryTests(unittest.TestCase):
    def test_catalog_requires_all_ordered_traits_and_groups_sql_synonyms(self):
        trait_rows = [
            SimpleNamespace(
                code=f"trait_{index}",
                name_zh=f"特質{index}",
                vector_index=index,
            )
            for index in range(PERSONALITY_DIMENSIONS)
        ]
        synonym_rows = [
            SimpleNamespace(trait_code=f"trait_{index}", term=f"同義詞{index}")
            for index in range(PERSONALITY_DIMENSIONS)
        ]
        repository = PersonalityRepository(_Session([trait_rows, synonym_rows]))

        catalog = repository.catalog()

        self.assertEqual(len(catalog.trait_names), PERSONALITY_DIMENSIONS)
        self.assertEqual(catalog.trait_names[10], "特質10")
        self.assertEqual(catalog.synonyms_by_trait["特質12"], ("同義詞12",))

    def test_catalog_rejects_missing_dimensions(self):
        rows = [SimpleNamespace(code="only", name_zh="唯一", vector_index=0)]

        with self.assertRaisesRegex(RuntimeError, "indexes 0-15"):
            PersonalityRepository(_Session([rows])).catalog()

    def test_sql_match_is_parameterized_and_returns_normalized_vector(self):
        session = _Session(
            [[
                SimpleNamespace(vector_index=2, score=2.0),
                SimpleNamespace(vector_index=10, score=2.0),
                SimpleNamespace(vector_index=12, score=2.0),
            ]]
        )

        vector = PersonalityRepository(session).vector_for_text(
            "我慢熟但重承諾，也喜歡與人分享"
        )

        self.assertEqual(len(vector), PERSONALITY_DIMENSIONS)
        self.assertAlmostEqual(sum(value * value for value in vector), 1.0)
        self.assertGreater(vector[2], 0)
        self.assertGreater(vector[10], 0)
        self.assertGreater(vector[12], 0)
        statement, params = session.calls[0]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.assertIn("strpos(", sql)
        self.assertNotIn("strpos(lower(", sql)
        self.assertIn("personality_trait_synonyms", sql)
        self.assertIn("normalized_term", sql)
        self.assertNotIn("我慢熟", sql)
        self.assertEqual(
            params["personality_query"],
            "我慢熟但重承諾,也喜歡與人分享",
        )

    def test_query_uses_nfkc_casefold_without_persisting_raw_text(self):
        session = _Session(
            [[SimpleNamespace(vector_index=4, score=2.0)]]
        )
        raw_query = "  ＲＥＬＩＡＢＬＥ\n"

        vector = PersonalityRepository(session).vector_for_text(raw_query)

        self.assertEqual(vector[4], 1.0)
        statement, params = session.calls[0]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.assertTrue(statement.is_select)
        self.assertEqual(params, {"personality_query": "reliable"})
        self.assertNotIn(raw_query, sql)
        self.assertIn("normalized_term", sql)

    def test_no_sql_matches_returns_zero_vector(self):
        vector = PersonalityRepository(_Session([[]])).vector_for_text("未知敘述")

        self.assertEqual(vector, (0.0,) * PERSONALITY_DIMENSIONS)


if __name__ == "__main__":
    unittest.main()
