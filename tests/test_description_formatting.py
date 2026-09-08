from __future__ import annotations

import csv
import unittest

from app.services.csv_importer import DEFAULT_CSV_PATH
from app.services.description_formatting import split_description_paragraphs


def _compact(value: str) -> str:
    return "".join(value.split())


def _display_length(value: str) -> int:
    return sum(1 for character in value if not character.isspace())


class DescriptionFormattingTests(unittest.TestCase):
    def test_source_line_breaks_are_hard_paragraph_boundaries(self):
        source = "第一段第一句。第一段第二句。\r\n\r\n第二段！\n第三段？"

        self.assertEqual(
            split_description_paragraphs(source),
            (
                "第一段第一句。第一段第二句。",
                "第二段！",
                "第三段？",
            ),
        )

    def test_sentences_are_grouped_by_sentence_and_character_limits(self):
        source = "第一句。第二句。第三句。第四句。"
        self.assertEqual(
            split_description_paragraphs(source, max_sentences=3),
            ("第一句。第二句。第三句。", "第四句。"),
        )

        long_sentence = f"{'甲' * 90}。"
        following_sentence = f"{'乙' * 90}。"
        self.assertEqual(
            split_description_paragraphs(long_sentence + following_sentence),
            (long_sentence, following_sentence),
        )

    def test_decimal_points_and_repeated_endings_preserve_the_original_text(self):
        source = "重量是40.0kg。Alpha. Beta.大量發生中！皮卡丘山谷!!"
        paragraphs = split_description_paragraphs(source, max_sentences=1)

        self.assertEqual(
            paragraphs,
            (
                "重量是40.0kg。",
                "Alpha.",
                "Beta.",
                "大量發生中！皮卡丘山谷!!",
            ),
        )
        self.assertEqual(_compact("".join(paragraphs)), _compact(source))

    def test_closing_quotes_semicolons_and_markup_remain_literal(self):
        source = "他說：「第一句。」接著離開；<script>不會執行</script>。"
        paragraphs = split_description_paragraphs(source, max_sentences=1)

        self.assertEqual(
            paragraphs,
            (
                "他說：「第一句。」",
                "接著離開；<script>不會執行</script>。",
            ),
        )
        self.assertEqual(_compact("".join(paragraphs)), _compact(source))

    def test_unusually_long_single_sentence_has_a_bounded_fallback(self):
        source = "甲" * 401
        paragraphs = split_description_paragraphs(source)

        self.assertEqual(
            [_display_length(paragraph) for paragraph in paragraphs],
            [160, 160, 81],
        )
        self.assertEqual("".join(paragraphs), source)

    def test_oversized_sentence_prefers_a_nearby_clause_boundary(self):
        source = f"{'甲' * 100}，{'乙' * 100}"
        paragraphs = split_description_paragraphs(source)

        self.assertEqual(paragraphs, (f"{'甲' * 100}，", "乙" * 100))
        self.assertEqual("".join(paragraphs), source)

    def test_oversized_chinese_exclamation_sentence_uses_natural_boundary(self):
        source = f"{'甲' * 100}！{'乙' * 100}。"
        paragraphs = split_description_paragraphs(source)

        self.assertEqual(paragraphs, (f"{'甲' * 100}！", f"{'乙' * 100}。"))
        self.assertEqual("".join(paragraphs), source)

    def test_exclamation_marks_inside_titles_do_not_create_paragraph_breaks(self):
        source = (
            "戴著帽子的皮卡丘會使用特殊招式。"
            "在阿羅拉最強的Ｚ！卡璞・鳴鳴VS皮卡丘!!中，"
            "牠會把十萬伏特轉化成千萬伏特。"
        )

        self.assertEqual(split_description_paragraphs(source), (source,))

    def test_invalid_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            split_description_paragraphs("文字。", max_characters=0)
        with self.assertRaises(ValueError):
            split_description_paragraphs("文字。", max_sentences=0)

    def test_all_1025_descriptions_are_preserved_and_readably_bounded(self):
        with DEFAULT_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 1025)
        total_paragraphs = 0
        for row in rows:
            with self.subTest(pokedex_number=row["pokedex_number"]):
                source = row["description_zh"]
                paragraphs = split_description_paragraphs(source)
                self.assertTrue(paragraphs)
                self.assertTrue(all(paragraph.strip() for paragraph in paragraphs))
                self.assertEqual(
                    _compact("".join(paragraphs)),
                    _compact(source),
                )
                self.assertLessEqual(
                    max(_display_length(paragraph) for paragraph in paragraphs),
                    160,
                )
                total_paragraphs += len(paragraphs)

        self.assertGreater(total_paragraphs, len(rows))


if __name__ == "__main__":
    unittest.main()
