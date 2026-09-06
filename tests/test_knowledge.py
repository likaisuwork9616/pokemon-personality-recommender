import unittest

from app.services.knowledge import build_knowledge_documents, split_knowledge_document
from app.services.csv_importer import read_csv_records


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

    def test_explicit_versions_change_lineage_ids(self):
        first = build_knowledge_documents(self.record)
        second = build_knowledge_documents(
            self.record,
            versions={"description_zh": 2},
        )

        self.assertEqual(second[1].version, 2)
        self.assertNotEqual(first[1].document_id, second[1].document_id)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            build_knowledge_documents(
                self.record,
                versions={"description_zh": 0},
            )

    def test_long_sentences_never_create_oversized_chunks(self):
        record = {**self.record, "description_zh": f"{'甲' * 90}。{'乙' * 90}。"}
        document = build_knowledge_documents(record)[1]

        chunks = split_knowledge_document(document, max_chars=100, overlap_chars=20)

        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(0 < chunk.char_count <= 100 for chunk in chunks))
        self.assertEqual(
            [chunk.chunk_index for chunk in chunks],
            list(range(len(chunks))),
        )

    def test_full_dataset_has_traceable_bounded_chunks(self):
        documents = []
        for record in read_csv_records():
            source = {
                **record.pokemon.__dict__,
                "type_zh": "canonical",
                **{
                    item.source_key.removeprefix("csv:"): item.content
                    for item in record.descriptions
                },
            }
            documents.extend(build_knowledge_documents(source))
        chunks = [
            chunk
            for document in documents
            for chunk in split_knowledge_document(document)
        ]

        self.assertEqual(len(documents), 4100)
        self.assertEqual(len(chunks), 4684)
        self.assertTrue(all(0 < chunk.char_count <= 500 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
