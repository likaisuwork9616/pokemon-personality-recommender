from __future__ import annotations

import io
import json
import logging
import unittest
from unittest.mock import patch
from uuid import UUID

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from app.db import Base
from app.main import create_app
from app.repositories.retrieval import RetrievalRepository
from app.repositories.vector import VectorRepository
from app.services.hybrid_retrieval import FusedChunkHit, PokemonRetrievalCandidate
from app.services.recommendation import (
    HybridRecommendationEngine,
    RetrievalUnavailableError,
)
import pokedex_online


def _public_result(rank: int) -> dict[str, object]:
    identity = f"00000000-0000-0000-0000-{rank:012x}"
    return {
        "rank": rank,
        "database_id": rank,
        "pokedex_number": rank,
        "name": f"寶可夢{rank}",
        "name_en": f"Pokemon {rank}",
        "type": "一般",
        "img": "",
        "scores": {"semantic": 0.8, "personality": 0.7, "total": 0.75},
        "matching_evidence": [
            {
                "evidence_id": f"ev_{rank:032x}",
                "document_id": identity,
                "chunk_id": identity,
                "source": "analysis_text",
                "document_kind": "analysis",
                "language_code": "mul",
                "text": "來源可追蹤的匹配證據",
                "content_hash": f"{rank:064x}",
                "dense_rank": rank,
                "dense_score": 0.8,
                "lexical_rank": None,
                "lexical_score": None,
                "rrf_score": 1 / (60 + rank),
                "matched_traits": ["忠誠守護者"],
            }
        ],
    }


class _PublicEngine:
    def __init__(self) -> None:
        self.explain_calls = 0

    @staticmethod
    def recommend(_text, top_k=3):
        return [_public_result(rank) for rank in range(1, top_k + 1)]

    def explain(self, _text, _pokemon):
        self.explain_calls += 1
        return "不應呼叫"


class ApiPrivacyTests(unittest.TestCase):
    def test_validation_error_does_not_echo_the_rejected_raw_text(self):
        marker = "PRIVATE-VALIDATION-MARKER"
        raw_text = marker + ("x" * 2100)

        with TestClient(create_app(_PublicEngine)) as client:
            response = client.post(
                "/api/v1/recommendations",
                json={"text": raw_text},
            )

        self.assertEqual(response.status_code, 422)
        self.assertNotIn(marker, response.text)
        self.assertNotIn('"input"', response.text)

    def test_success_does_not_echo_or_log_query_and_ai_stays_opt_in(self):
        marker = "PRIVATE-SUCCESS-MARKER"
        engine = _PublicEngine()
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            with TestClient(create_app(lambda: engine)) as client:
                response = client.post(
                    "/api/v1/recommendations",
                    json={"text": marker},
                )
        finally:
            root_logger.removeHandler(handler)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(marker, response.text)
        self.assertNotIn(marker, log_stream.getvalue())
        self.assertEqual(engine.explain_calls, 0)
        self.assertFalse(self._contains_384_value_list(response.json()))

    def test_retrieval_error_response_never_contains_raw_query(self):
        marker = "PRIVATE-ERROR-MARKER"

        class BrokenEngine(_PublicEngine):
            @staticmethod
            def recommend(text, top_k=3):
                raise RetrievalUnavailableError("hybrid retrieval is unavailable")

        with TestClient(create_app(BrokenEngine)) as client:
            response = client.post(
                "/api/v1/recommendations",
                json={"text": marker},
            )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn(marker, response.text)

    @classmethod
    def _contains_384_value_list(cls, value) -> bool:
        if isinstance(value, list):
            return len(value) == 384 or any(cls._contains_384_value_list(item) for item in value)
        if isinstance(value, dict):
            return any(cls._contains_384_value_list(item) for item in value.values())
        return False


class QueryPersistenceTests(unittest.TestCase):
    def test_retrieval_repositories_execute_selects_only(self):
        class CaptureSession:
            def __init__(self):
                self.statements = []

            def execute(self, statement):
                self.statements.append(statement)
                return []

        dense_session = CaptureSession()
        lexical_session = CaptureSession()

        VectorRepository(dense_session).exact_search(
            query_vector=[1.0, *([0.0] * 383)],
            embedding_model_id=1,
        )
        RetrievalRepository(lexical_session).lexical_search(tokens=("守護",))

        self.assertTrue(dense_session.statements[0].is_select)
        self.assertTrue(lexical_session.statements[0].is_select)
        self.assertFalse(any("query" in table_name for table_name in Base.metadata.tables))

    def test_hybrid_engine_does_not_retain_raw_query_or_query_vector(self):
        marker = "PRIVATE-IN-MEMORY-MARKER"

        class Encoder:
            @staticmethod
            def encode(_text, **_kwargs):
                return np.array([1.0, *([0.0] * 383)])

        class Profile:
            id_col = "pokedex_number"
            name_col = "name_zh"
            name_en_col = "name_en"
            type_col = "type_zh"
            type_1_col = "type_1"
            type_2_col = "type_2"
            cat_col = "category_zh"
            genus_col = "genus"
            desc_col = "description_zh"
            flavor_en_col = "flavor_text_en"
            analysis_col = "analysis_text"
            img_col = "image_url"
            sprite_col = "sprite_url"

            def __init__(self):
                self.st_model = Encoder()
                self.df = pd.DataFrame(
                    [
                        {
                            "_database_id": number,
                            "_form_key": "default",
                            "pokedex_number": number,
                            "name_zh": f"寶可夢{number}",
                            "name_en": f"Pokemon {number}",
                            "type_zh": "一般",
                            "type_1": "Normal",
                            "type_2": "Unknown",
                            "category_zh": "分類",
                            "genus": "Genus",
                            "description_zh": "資料庫內容",
                            "flavor_text_en": "Database content",
                            "analysis_text": "人格資料",
                            "image_url": "",
                            "sprite_url": "",
                        }
                        for number in (1, 2, 3)
                    ]
                )
                self.persona_vectors = np.zeros((3, 16))

            @staticmethod
            def text_to_persona_vector(_text):
                return np.zeros(16)

            @staticmethod
            def get_top_traits(_vector):
                return []

            @staticmethod
            def safe_get(row, column, default=""):
                return row.get(column, default)

            @staticmethod
            def explain(_text, _pokemon):
                return ""

        def candidate(number: int) -> PokemonRetrievalCandidate:
            identity = UUID(int=number)
            hit = FusedChunkHit(
                pokemon_id=number,
                document_id=identity,
                chunk_id=identity,
                source_key="analysis_text",
                document_kind="analysis",
                language_code="mul",
                content="資料庫證據",
                content_hash=f"{number:064x}",
                dense_rank=number,
                dense_score=0.8,
                lexical_rank=None,
                lexical_score=None,
                rrf_score=1 / (60 + number),
            )
            return PokemonRetrievalCandidate(
                pokemon_id=number,
                retrieval_score=hit.rrf_score,
                best_chunk_score=hit.rrf_score,
                best_branch_rank=number,
                evidence=(hit,),
            )

        class Retriever:
            @staticmethod
            def retrieve(**_kwargs):
                return [candidate(number) for number in (1, 2, 3)]

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        engine = HybridRecommendationEngine(
            profile_engine=Profile(),
            session_factory=Session,
            embedding_model_id=1,
            retrieval_service_factory=lambda _session: Retriever(),
        )

        result = engine.recommend(marker)

        self.assertNotIn(marker, repr(vars(engine)))
        self.assertNotIn(marker, json.dumps(result, ensure_ascii=False))
        self.assertFalse(any("query" in key.casefold() for key in vars(engine)))


class ProviderErrorPrivacyTests(unittest.TestCase):
    def test_legacy_provider_failure_does_not_surface_provider_exception(self):
        marker = "PRIVATE-PROVIDER-ERROR-MARKER"

        class Responses:
            @staticmethod
            def create(**_kwargs):
                raise RuntimeError(marker)

        client = type("Client", (), {"responses": Responses()})()
        engine = object.__new__(pokedex_online.PokemonRecommender)
        pokemon = {
            "name": "測試寶可夢",
            "name_en": "Test Pokemon",
            "type": "一般",
            "type_en": "Normal",
            "category": "測試",
            "genus": "Test",
            "user_traits": [],
            "pokemon_traits": [],
            "desc": "本機證據",
            "flavor_text_en": "Local evidence",
            "analysis_text": "本機分析",
        }

        with patch.object(pokedex_online, "client", client):
            explanation = engine.explain("不應回顯的查詢", pokemon)

        self.assertNotIn(marker, explanation)
        self.assertNotIn("暫時失敗", explanation)


if __name__ == "__main__":
    unittest.main()
