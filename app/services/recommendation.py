"""Database-backed recommendation orchestration for Hybrid Retrieval."""

from __future__ import annotations

from threading import Lock
from typing import Any, Callable

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from app.repositories.retrieval import RetrievalRepository
from app.repositories.vector import VectorRepository
from app.services.hybrid_retrieval import HybridRetrievalService, RRF_K


class RetrievalUnavailableError(RuntimeError):
    """Raised when the indexed corpus cannot produce a complete Top 3."""


class HybridRecommendationEngine:
    """Combine PostgreSQL retrieval with the existing deterministic persona rules.

    The wrapped profile engine owns the read-only Pokémon dataframe, personality
    vectors and sentence encoder. Database sessions and every query-derived value
    remain local to :meth:`recommend`.
    """

    def __init__(
        self,
        *,
        profile_engine: Any,
        session_factory: Callable[[], Any],
        embedding_model_id: int,
        retrieval_service_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        self.profile_engine = profile_engine
        self.session_factory = session_factory
        self.embedding_model_id = int(embedding_model_id)
        self._retrieval_service_factory = retrieval_service_factory or (
            lambda session: HybridRetrievalService(
                VectorRepository(session),
                RetrievalRepository(session),
            )
        )
        self._encode_lock = Lock()

        database_ids: dict[int, int] = {}
        for row_index, value in enumerate(profile_engine.df["_database_id"].tolist()):
            database_id = int(value)
            if database_id in database_ids:
                raise ValueError(f"duplicate PostgreSQL Pokémon ID: {database_id}")
            database_ids[database_id] = row_index
        self._row_index_by_database_id = database_ids

    def recommend(self, user_text: str, top_k: int = 3) -> list[dict[str, Any]]:
        text = str(user_text).strip()
        if not text:
            raise ValueError("使用者輸入不可為空。")
        if not 1 <= top_k <= 10:
            raise ValueError("top_k 必須介於 1 到 10。")

        # SentenceTransformer/tokenizer inference is process-local and may not be
        # safe under concurrent request threads. Only the encode call is locked.
        try:
            with self._encode_lock:
                encoded = self.profile_engine.st_model.encode(
                    text,
                    normalize_embeddings=True,
                )
            encoded_array = np.asarray(encoded, dtype=float)
            if encoded_array.shape != (384,) or not np.isfinite(encoded_array).all():
                raise ValueError("unexpected query vector shape or values")
            query_vector = encoded_array.tolist()
        except Exception as exc:
            raise RetrievalUnavailableError(
                "query encoder is temporarily unavailable"
            ) from exc

        try:
            with self.session_factory() as session:
                candidates = self._retrieval_service_factory(session).retrieve(
                    query_text=text,
                    query_vector=query_vector,
                    embedding_model_id=self.embedding_model_id,
                    pokemon_limit=50,
                )
        except RetrievalUnavailableError:
            raise
        except Exception as exc:
            raise RetrievalUnavailableError(
                "hybrid retrieval is temporarily unavailable"
            ) from exc

        user_persona = self.profile_engine.text_to_persona_vector(text)
        alpha = min(0.8, 0.35 + float(np.linalg.norm(user_persona)) * 0.35)
        max_rrf_score = 2.0 / (RRF_K + 1)
        ranked: list[tuple[tuple[float, float, float, int, str, int], dict[str, Any]]] = []
        seen_candidate_ids: set[int] = set()

        for candidate in candidates:
            if candidate.pokemon_id in seen_candidate_ids:
                raise RetrievalUnavailableError(
                    "hybrid index returned duplicate Pokémon candidates"
                )
            seen_candidate_ids.add(candidate.pokemon_id)
            row_index = self._row_index_by_database_id.get(candidate.pokemon_id)
            if row_index is None:
                raise RetrievalUnavailableError(
                    "runtime Pokémon profile snapshot is stale"
                )
            row = self.profile_engine.df.iloc[row_index]
            pokemon_persona = self.profile_engine.persona_vectors[row_index]
            personality = float(
                np.clip(cosine_similarity([user_persona], [pokemon_persona])[0][0], 0, 1)
            )
            semantic = float(np.clip(candidate.retrieval_score / max_rrf_score, 0, 1))
            total = float(np.clip(alpha * personality + (1.0 - alpha) * semantic, 0, 1))
            pokemon_traits = self.profile_engine.get_top_traits(pokemon_persona)

            pokedex_value = row[self.profile_engine.id_col]
            pokedex_number = (
                int(pokedex_value)
                if str(pokedex_value).isdigit()
                else pokedex_value
            )
            result = {
                "database_id": candidate.pokemon_id,
                "pokedex_number": pokedex_number,
                "name": self.profile_engine.safe_get(row, self.profile_engine.name_col),
                "name_en": self.profile_engine.safe_get(row, self.profile_engine.name_en_col),
                "type": self.profile_engine.safe_get(row, self.profile_engine.type_col),
                "type_en": ", ".join(
                    [
                        str(self.profile_engine.safe_get(row, self.profile_engine.type_1_col)),
                        str(self.profile_engine.safe_get(row, self.profile_engine.type_2_col)),
                    ]
                ).strip(", "),
                "category": self.profile_engine.safe_get(row, self.profile_engine.cat_col),
                "genus": self.profile_engine.safe_get(row, self.profile_engine.genus_col),
                "desc": self.profile_engine.safe_get(row, self.profile_engine.desc_col),
                "flavor_text_en": self.profile_engine.safe_get(
                    row, self.profile_engine.flavor_en_col
                ),
                "analysis_text": self.profile_engine.safe_get(
                    row, self.profile_engine.analysis_col
                ),
                "img": self.profile_engine.safe_get(row, self.profile_engine.img_col)
                or self.profile_engine.safe_get(row, self.profile_engine.sprite_col),
                "scores": {
                    "semantic": semantic,
                    "personality": personality,
                    "total": total,
                },
                "matching_evidence": [
                    {
                        "source": evidence.source_key,
                        "text": evidence.content[:240],
                        "matched_traits": pokemon_traits,
                        # The current response schema ignores these lineage fields;
                        # MVP-02 promotes them into the public evidence contract.
                        "document_id": str(evidence.document_id),
                        "chunk_id": str(evidence.chunk_id),
                        "dense_rank": evidence.dense_rank,
                        "lexical_rank": evidence.lexical_rank,
                        "rrf_score": evidence.rrf_score,
                    }
                    for evidence in candidate.evidence
                ],
                "user_traits": self.profile_engine.get_top_traits(user_persona),
                "pokemon_traits": pokemon_traits,
            }
            ranked.append(
                (
                    (
                        -total,
                        -semantic,
                        -personality,
                        int(pokedex_number),
                        str(row.get("_form_key", "default")),
                        candidate.pokemon_id,
                    ),
                    result,
                )
            )

        ranked.sort(key=lambda item: item[0])
        selected = ranked[:top_k]
        if len(selected) != top_k:
            raise RetrievalUnavailableError(
                f"hybrid index returned only {len(selected)} unique Pokémon"
            )
        results: list[dict[str, Any]] = []
        for rank, (_sort_key, result) in enumerate(selected, start=1):
            result["rank"] = rank
            results.append(result)
        return results

    def explain(self, user_text: str, pokemon: dict[str, Any]) -> str:
        """Compatibility bridge until the grounded RAG chapter replaces it."""

        return self.profile_engine.explain(user_text, pokemon)
