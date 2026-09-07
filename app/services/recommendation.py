"""Database-backed recommendation orchestration for Hybrid Retrieval."""

from __future__ import annotations

from copy import copy
from threading import Lock
from typing import Any, Callable

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from app.repositories.retrieval import RetrievalRepository
from app.repositories.personality import PersonalityRepository
from app.repositories.vector import VectorRepository
from app.services.hybrid_retrieval import HybridRetrievalService, RRF_K
from app.services.rag import GroundedExplanationService


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
        personality_repository_factory: Callable[[Any], Any] | None = None,
        explanation_service: GroundedExplanationService | None = None,
        profile_records_loader: Callable[[], list[dict[str, object]]] | None = None,
        personality_revision: int | None = None,
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
        self._personality_repository_factory = personality_repository_factory or (
            lambda session: PersonalityRepository(session)
        )
        self.explanation_service = explanation_service or GroundedExplanationService()
        self._encode_lock = Lock()
        self._profile_refresh_lock = Lock()
        self._profile_records_loader = profile_records_loader
        self._personality_revision = personality_revision

        database_ids = self._database_id_map(profile_engine)
        self._profile_state = (profile_engine, database_ids)

    @staticmethod
    def _database_id_map(profile_engine: Any) -> dict[int, int]:
        database_ids: dict[int, int] = {}
        for row_index, value in enumerate(profile_engine.df["_database_id"].tolist()):
            database_id = int(value)
            if database_id in database_ids:
                raise ValueError(f"duplicate PostgreSQL Pokémon ID: {database_id}")
            database_ids[database_id] = row_index
        return database_ids

    def refresh_profiles(self) -> int:
        """Atomically replace the in-memory personality snapshot from PostgreSQL."""

        if self._profile_records_loader is None:
            raise RuntimeError("profile refresh is not configured")
        with self._profile_refresh_lock:
            records = self._profile_records_loader()
            if len(records) < 3:
                raise RuntimeError("profile refresh returned fewer than three Pokémon")
            import pandas as pd

            current, _current_ids = self._profile_state
            refreshed = copy(current)
            refreshed.df = pd.DataFrame.from_records(records).fillna("")
            refreshed._validate_columns()
            refreshed.persona_vectors = refreshed.build_persona_vectors()
            database_ids = self._database_id_map(refreshed)
            self.profile_engine = refreshed
            self._profile_state = (refreshed, database_ids)
            return len(records)

    def refresh_personality_catalog(self, catalog: Any, *, revision: int | None = None) -> int:
        """Atomically rebuild profile vectors after vocabulary administration."""

        with self._profile_refresh_lock:
            if revision is not None and revision == self._personality_revision:
                return len(catalog.trait_names)
            current, database_ids = self._profile_state
            refreshed = copy(current)
            refreshed.traits = tuple(catalog.trait_names)
            refreshed.persona_keywords = {
                trait: list(catalog.synonyms_by_trait[trait])
                for trait in refreshed.traits
            }
            refreshed.persona_vectors = refreshed.build_persona_vectors()
            self.profile_engine = refreshed
            self._profile_state = (refreshed, database_ids)
            if revision is not None:
                self._personality_revision = revision
            return len(refreshed.traits)

    def _refresh_personality_if_stale(self, repository: Any) -> None:
        revision_reader = getattr(repository, "revision", None)
        catalog_reader = getattr(repository, "catalog", None)
        if not callable(revision_reader) or not callable(catalog_reader):
            return
        revision = int(revision_reader())
        if self._personality_revision is None:
            self._personality_revision = revision
            return
        if revision != self._personality_revision:
            self.refresh_personality_catalog(catalog_reader(), revision=revision)

    def recommend(self, user_text: str, top_k: int = 3) -> list[dict[str, Any]]:
        text = str(user_text).strip()
        if not text:
            raise ValueError("使用者輸入不可為空。")
        if not 1 <= top_k <= 10:
            raise ValueError("top_k 必須介於 1 到 10。")
        profile_engine, row_index_by_database_id = self._profile_state

        # SentenceTransformer/tokenizer inference is process-local and may not be
        # safe under concurrent request threads. Only the encode call is locked.
        try:
            with self._encode_lock:
                encoded = profile_engine.st_model.encode(
                    text,
                    normalize_embeddings=True,
                )
            encoded_array = np.asarray(encoded, dtype=float)
            if encoded_array.shape != (384,) or not np.isfinite(encoded_array).all():
                raise ValueError("unexpected query vector shape or values")
            query_vector = encoded_array.tolist()
        except Exception:
            raise RetrievalUnavailableError(
                "query encoder is temporarily unavailable"
            ) from None

        try:
            with self.session_factory() as session:
                candidates = self._retrieval_service_factory(session).retrieve(
                    query_text=text,
                    query_vector=query_vector,
                    embedding_model_id=self.embedding_model_id,
                    pokemon_limit=50,
                )
                try:
                    personality_repository = self._personality_repository_factory(session)
                    self._refresh_personality_if_stale(personality_repository)
                    profile_engine, row_index_by_database_id = self._profile_state
                    user_persona = np.asarray(
                        personality_repository.vector_for_text(text),
                        dtype=float,
                    )
                    if user_persona.shape != (16,) or not np.isfinite(user_persona).all():
                        raise ValueError("unexpected personality vector")
                except Exception:
                    raise RetrievalUnavailableError(
                        "personality scoring is temporarily unavailable"
                    ) from None
        except RetrievalUnavailableError:
            raise
        except Exception:
            raise RetrievalUnavailableError(
                "hybrid retrieval is temporarily unavailable"
            ) from None

        if (
            self._profile_records_loader is not None
            and any(
                candidate.pokemon_id not in row_index_by_database_id
                for candidate in candidates
            )
        ):
            try:
                self.refresh_profiles()
                profile_engine, row_index_by_database_id = self._profile_state
            except Exception:
                raise RetrievalUnavailableError(
                    "runtime Pokémon profile snapshot is stale"
                ) from None

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
            row_index = row_index_by_database_id.get(candidate.pokemon_id)
            if row_index is None:
                raise RetrievalUnavailableError(
                    "runtime Pokémon profile snapshot is stale"
                )
            row = profile_engine.df.iloc[row_index]
            pokemon_persona = profile_engine.persona_vectors[row_index]
            personality = float(
                np.clip(cosine_similarity([user_persona], [pokemon_persona])[0][0], 0, 1)
            )
            semantic = float(np.clip(candidate.retrieval_score / max_rrf_score, 0, 1))
            total = float(np.clip(alpha * personality + (1.0 - alpha) * semantic, 0, 1))
            pokemon_traits = profile_engine.get_top_traits(pokemon_persona)

            pokedex_value = row[profile_engine.id_col]
            pokedex_number = (
                int(pokedex_value)
                if str(pokedex_value).isdigit()
                else pokedex_value
            )
            result = {
                "database_id": candidate.pokemon_id,
                "pokedex_number": pokedex_number,
                "name": profile_engine.safe_get(row, profile_engine.name_col),
                "name_en": profile_engine.safe_get(row, profile_engine.name_en_col),
                "type": profile_engine.safe_get(row, profile_engine.type_col),
                "type_en": ", ".join(
                    [
                        str(profile_engine.safe_get(row, profile_engine.type_1_col)),
                        str(profile_engine.safe_get(row, profile_engine.type_2_col)),
                    ]
                ).strip(", "),
                "category": profile_engine.safe_get(row, profile_engine.cat_col),
                "genus": profile_engine.safe_get(row, profile_engine.genus_col),
                "desc": profile_engine.safe_get(row, profile_engine.desc_col),
                "flavor_text_en": profile_engine.safe_get(
                    row, profile_engine.flavor_en_col
                ),
                "analysis_text": profile_engine.safe_get(
                    row, profile_engine.analysis_col
                ),
                "img": profile_engine.safe_get(row, profile_engine.img_col)
                or profile_engine.safe_get(row, profile_engine.sprite_col),
                "scores": {
                    "semantic": round(semantic, 8),
                    "personality": round(personality, 8),
                    "total": round(total, 8),
                },
                "matching_evidence": [
                    {
                        "evidence_id": f"ev_{evidence.chunk_id.hex}",
                        "document_id": str(evidence.document_id),
                        "chunk_id": str(evidence.chunk_id),
                        "source": evidence.source_key,
                        "document_kind": evidence.document_kind,
                        "language_code": evidence.language_code,
                        "text": evidence.content[:240],
                        "content_hash": evidence.content_hash,
                        "dense_rank": evidence.dense_rank,
                        "dense_score": (
                            round(float(np.clip(evidence.dense_score, -1, 1)), 8)
                            if evidence.dense_score is not None
                            else None
                        ),
                        "lexical_rank": evidence.lexical_rank,
                        "lexical_score": (
                            round(max(0.0, evidence.lexical_score), 8)
                            if evidence.lexical_score is not None
                            else None
                        ),
                        "rrf_score": round(evidence.rrf_score, 10),
                        "matched_traits": pokemon_traits,
                    }
                    for evidence in candidate.evidence
                ],
                "user_traits": profile_engine.get_top_traits(user_persona),
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

    def explain_results(
        self,
        user_text: str,
        pokemon_results: list[dict[str, Any]],
    ) -> dict[int, dict[str, object]]:
        explanations = self.explanation_service.explain_many(
            user_text,
            pokemon_results,
        )
        return {
            pokemon_id: explanation.as_dict()
            for pokemon_id, explanation in explanations.items()
        }

    def explain(self, user_text: str, pokemon: dict[str, Any]) -> dict[str, object]:
        """Generate one grounded explanation for compatibility callers."""

        return self.explain_results(user_text, [pokemon])[int(pokemon["database_id"])]
