from __future__ import annotations

import copy
import unittest

from pydantic import ValidationError

from app.schemas.recommendation import EvidenceResponse, RecommendationResponse


def _evidence(number: int) -> dict[str, object]:
    return {
        "evidence_id": f"ev_{number:032x}",
        "document_id": f"00000000-0000-0000-0000-{number:012x}",
        "chunk_id": f"00000000-0000-0000-0000-{number:012x}",
        "source": "analysis_text",
        "document_kind": "analysis",
        "language_code": "mul",
        "text": "重視夥伴並安靜守護群體。",
        "content_hash": f"{number:064x}",
        "dense_rank": number,
        "dense_score": 0.82,
        "lexical_rank": number,
        "lexical_score": 0.41,
        "rrf_score": 2 / (60 + number),
        "matched_traits": ["忠誠守護者"],
    }


def _result(number: int) -> dict[str, object]:
    return {
        "rank": number,
        "pokemon": {
            "id": number,
            "pokedex_number": number,
            "name_zh": f"寶可夢{number}",
            "name_en": f"Pokemon {number}",
            "types": "一般",
            "image_url": None,
        },
        "scores": {
            "semantic": 0.8,
            "personality": 0.7,
            "total": 0.75,
        },
        "evidence": [_evidence(number)],
        "explanation": None,
    }


class RecommendationSchemaTests(unittest.TestCase):
    def test_response_requires_exact_ordered_unique_top_three(self):
        valid = [_result(number) for number in (1, 2, 3)]

        response = RecommendationResponse(results=valid)

        self.assertEqual([item.rank for item in response.results], [1, 2, 3])
        for invalid in (
            valid[:2],
            [valid[1], valid[0], valid[2]],
            [valid[0], valid[0], valid[2]],
        ):
            with self.assertRaises(ValidationError):
                RecommendationResponse(results=invalid)

    def test_evidence_requires_complete_branch_rank_and_score_pairs(self):
        dense_only = _evidence(1)
        dense_only["lexical_rank"] = None
        dense_only["lexical_score"] = None
        self.assertIsNotNone(EvidenceResponse.model_validate(dense_only))

        missing_dense_score = copy.deepcopy(dense_only)
        missing_dense_score["dense_score"] = None
        with self.assertRaises(ValidationError):
            EvidenceResponse.model_validate(missing_dense_score)

        no_branch = copy.deepcopy(dense_only)
        no_branch["dense_rank"] = None
        no_branch["dense_score"] = None
        with self.assertRaises(ValidationError):
            EvidenceResponse.model_validate(no_branch)

    def test_lineage_ids_hashes_and_score_ranges_are_strict(self):
        invalid_id = _evidence(1)
        invalid_id["evidence_id"] = "evidence-one"
        with self.assertRaises(ValidationError):
            EvidenceResponse.model_validate(invalid_id)

        invalid_hash = _evidence(1)
        invalid_hash["content_hash"] = "not-a-sha256"
        with self.assertRaises(ValidationError):
            EvidenceResponse.model_validate(invalid_hash)

        invalid_dense_score = _evidence(1)
        invalid_dense_score["dense_score"] = 1.1
        with self.assertRaises(ValidationError):
            EvidenceResponse.model_validate(invalid_dense_score)

    def test_explanation_may_only_cite_its_own_evidence(self):
        valid = [_result(number) for number in (1, 2, 3)]
        valid[0]["explanation"] = {
            "text": "這段說明只根據同一筆推薦的檢索證據。",
            "citations": [f"ev_{1:032x}"],
            "provider": "gemini",
            "grounded": True,
            "used_fallback": False,
        }
        self.assertIsNotNone(RecommendationResponse(results=valid))

        invalid = copy.deepcopy(valid)
        invalid[0]["explanation"]["citations"] = [f"ev_{2:032x}"]
        with self.assertRaises(ValidationError):
            RecommendationResponse(results=invalid)

        secondary_explanation = copy.deepcopy(valid)
        secondary_explanation[1]["explanation"] = {
            "text": "第二名不應執行或回傳額外的模型分析。",
            "citations": [f"ev_{2:032x}"],
            "provider": "gemini",
            "grounded": True,
            "used_fallback": False,
        }
        with self.assertRaisesRegex(ValidationError, "top-ranked"):
            RecommendationResponse(results=secondary_explanation)


if __name__ == "__main__":
    unittest.main()
