from __future__ import annotations

import unittest
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.repositories.personality import PERSONALITY_DIMENSIONS, PersonalityRepository


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append((statement, params))
        return _Rows(self.rows)


def vocabulary_rows(*, revision: int | None = 7):
    return [
        SimpleNamespace(
            revision=revision,
            code=f"trait_{index}",
            name_zh=f"特質{index}",
            vector_index=index,
            term=f"詞{index}",
            language_code="zh-Hant",
            weight=2.0,
        )
        for index in range(PERSONALITY_DIMENSIONS)
    ]


class PublicPersonalityRepositoryTests(unittest.TestCase):
    def test_public_catalog_is_active_only_and_stably_orders_weighted_terms(self):
        rows = vocabulary_rows()
        rows.extend(
            [
                SimpleNamespace(
                    revision=7,
                    code="trait_0",
                    name_zh="特質0",
                    vector_index=0,
                    term="english-heavy",
                    language_code="en",
                    weight=5.0,
                ),
                SimpleNamespace(
                    revision=7,
                    code="trait_0",
                    name_zh="特質0",
                    vector_index=0,
                    term="中文乙",
                    language_code="zh-Hant",
                    weight=3.0,
                ),
                SimpleNamespace(
                    revision=7,
                    code="trait_0",
                    name_zh="特質0",
                    vector_index=0,
                    term="中文甲",
                    language_code="zh-Hant",
                    weight=3.0,
                ),
            ]
        )
        session = _Session(list(reversed(rows)))

        catalog = PersonalityRepository(session).public_catalog()

        self.assertEqual(catalog.revision, 7)
        self.assertEqual(len(catalog.traits), PERSONALITY_DIMENSIONS)
        self.assertEqual(
            [trait.code for trait in catalog.traits],
            [f"trait_{index}" for index in range(PERSONALITY_DIMENSIONS)],
        )
        self.assertEqual(
            [term.term for term in catalog.traits[0].weighted_terms],
            ["中文乙", "中文甲", "詞0", "english-heavy"],
        )
        self.assertEqual(
            [term.weight for term in catalog.traits[0].weighted_terms],
            [3.0, 3.0, 2.0, 5.0],
        )

        statement, params = session.statements[0]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.assertIsNone(params)
        self.assertIn("personality_traits.is_active IS true", sql)
        self.assertIn("personality_trait_synonyms.is_active IS true", sql)
        self.assertIn("personality_vocabulary_state.revision", sql)

    def test_public_catalog_rejects_missing_dimensions(self):
        rows = vocabulary_rows()[:-1]

        with self.assertRaisesRegex(RuntimeError, "indexes 0-15"):
            PersonalityRepository(_Session(rows)).public_catalog()

    def test_public_catalog_requires_a_revision(self):
        with self.assertRaisesRegex(RuntimeError, "revision is missing"):
            PersonalityRepository(
                _Session(vocabulary_rows(revision=None))
            ).public_catalog()


if __name__ == "__main__":
    unittest.main()
