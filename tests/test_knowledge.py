import unittest

from app.services.knowledge import build_knowledge_documents, split_knowledge_document


class KnowledgePipelineTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "pokedex_number": 1,
            "name_zh": "妙蛙種子",
            "name_en": "Bulbasaur",
            "type_zh": "草, 毒",
            "description_zh": "牠會在陽光下休息。背上的種子會逐漸成長。",
            "flavor_text_en": "A seed grows on its back.",
            "analysis_text": "個性沉穩，也重視夥伴。",
        }

    def test_documents_keep_source_lineage(self):
        documents = build_knowledge_documents(self.record)

        self.assertEqual(
            [document.source_key for document in documents],
            ["profile", "description_zh", "flavor_text_en", "analysis_text"],
        )
        self.assertTrue(all(len(document.content_hash) == 64 for document in documents))

    def test_document_and_chunk_ids_are_deterministic(self):
        first = build_knowledge_documents(self.record)
        second = build_knowledge_documents(self.record)

        self.assertEqual(first, second)
        self.assertEqual(
            split_knowledge_document(first[1]),
            split_knowledge_document(second[1]),
        )

    def test_chunks_include_search_and_traceability_metadata(self):
        document = build_knowledge_documents(self.record)[1]
        chunks = split_knowledge_document(document, max_chars=100, overlap_chars=20)

        self.assertGreaterEqual(len(chunks), 1)
        self.assertEqual(chunks[0].document_id, document.document_id)
        self.assertIn("陽光", chunks[0].lexical_text)
        self.assertEqual(chunks[0].char_count, len(chunks[0].content))


if __name__ == "__main__":
    unittest.main()
