"""Read-only hybrid retrieval with local, versioned MBTI reference affinities."""

from __future__ import annotations

from copy import copy
from dataclasses import replace
from threading import Lock
from typing import Any, Callable

import numpy as np

from app.repositories.mbti_profiles import MbtiProfileRepository
from app.repositories.retrieval import RetrievalRepository
from app.repositories.vector import VectorRepository
from app.services.hybrid_retrieval import HybridRetrievalService, RRF_K
from app.services.mbti_scoring import MbtiScorer, normalized_embedding
from app.services.rag import GroundedExplanationService
from app.services.reranking import CrossEncoderReranker


class RetrievalUnavailableError(RuntimeError):
    """Raised when the indexed corpus cannot produce complete recommendations."""


class HybridRecommendationEngine:
    """Keep catalog prototypes immutable and request-derived signals local."""

    def __init__(
        self, *, profile_engine: Any, session_factory: Callable[[], Any],
        embedding_model_id: int,
        retrieval_service_factory: Callable[[Any], Any] | None = None,
        mbti_profile_repository_factory: Callable[[Any], Any] | None = None,
        mbti_catalog: Any | None = None,
        mbti_scorer: MbtiScorer | None = None,
        explanation_service: GroundedExplanationService | None = None,
        profile_records_loader: Callable[[], list[dict[str, object]]] | None = None,
        mbti_provider: Any | None = None,
        embedding_model_key: tuple | None = None,
        reranker: CrossEncoderReranker | None = None,
        database_readiness_probe: Any | None = None,
        personality_trait_codes: tuple[str, ...] | None = None,
    ) -> None:
        self.profile_engine = profile_engine
        self.session_factory = session_factory
        self.embedding_model_id = int(embedding_model_id)
        self._retrieval_service_factory = retrieval_service_factory or (
            lambda session: HybridRetrievalService(VectorRepository(session), RetrievalRepository(session))
        )
        self._mbti_profile_repository_factory = mbti_profile_repository_factory or MbtiProfileRepository
        self.explanation_service = explanation_service or GroundedExplanationService()
        self._encode_lock = Lock()
        self._profile_refresh_lock = Lock()
        self._profile_records_loader = profile_records_loader
        self.mbti_provider = mbti_provider
        self.embedding_model_key = embedding_model_key or (self.embedding_model_id, "unknown", "default", 384, True)
        self.reranker = reranker
        self.database_readiness_probe = database_readiness_probe
        self.personality_trait_codes = personality_trait_codes

        if mbti_scorer is None and mbti_provider is not None:
            mbti_scorer = mbti_provider.scorer(profile_engine.st_model, self.embedding_model_key, self._encode_lock)
        if mbti_scorer is None:
            if mbti_catalog is None:
                from app.services.mbti_catalog import get_mbti_catalog
                mbti_catalog = get_mbti_catalog()
            mbti_scorer = MbtiScorer.from_encoder(mbti_catalog, profile_engine.st_model)
        self.mbti_scorer = mbti_scorer
        self.mbti_catalog = mbti_scorer.catalog
        self._profile_state = (profile_engine, self._database_id_map(profile_engine))

    @staticmethod
    def _database_id_map(profile_engine: Any) -> dict[int, int]:
        database_ids: dict[int, int] = {}
        for row_index, value in enumerate(profile_engine.df["_database_id"].tolist()):
            database_id = int(value)
            if database_id in database_ids:
                raise ValueError("duplicate PostgreSQL Pokémon ID")
            database_ids[database_id] = row_index
        return database_ids

    def refresh_profiles(self) -> int:
        """Replace display metadata only; scoring always reads the ready index."""

        if self._profile_records_loader is None:
            raise RuntimeError("profile refresh is not configured")
        with self._profile_refresh_lock:
            records = self._profile_records_loader()
            if len(records) < 3:
                raise RuntimeError("profile refresh returned fewer than three Pokémon")
            import pandas as pd

            current, _ids = self._profile_state
            refreshed = copy(current)
            refreshed.df = pd.DataFrame.from_records(records).fillna("")
            refreshed._validate_columns()
            self._profile_state = (refreshed, self._database_id_map(refreshed))
            self.profile_engine = refreshed
            return len(records)

    @property
    def personality_refresh_healthy(self) -> bool:
        """The bundled catalog is validated once; no database vocabulary refresh."""

        return self.mbti_provider is None or self.mbti_provider.refresh_healthy

    def _selected_mbti(self, value: str | None) -> str | None:
        from app.services.mbti_catalog import normalize_mbti

        return normalize_mbti(value)

    @staticmethod
    def _union_candidates(text_candidates, mbti_candidates):
        """Preserve text RRF and prefer text metadata for duplicate chunks."""

        merged = {}
        for branch, candidates in enumerate((text_candidates, mbti_candidates)):
            seen = set()
            if len(candidates) > 50:
                raise RetrievalUnavailableError("hybrid index exceeded the candidate limit")
            for candidate in candidates:
                if candidate.pokemon_id in seen:
                    raise RetrievalUnavailableError("hybrid index returned duplicate Pokémon candidates")
                seen.add(candidate.pokemon_id)
                previous = merged.get(candidate.pokemon_id)
                if previous is None:
                    merged[candidate.pokemon_id] = replace(
                        candidate, retrieval_score=candidate.retrieval_score if branch == 0 else 0.0,
                        evidence=tuple(candidate.evidence[:3]),
                    )
                    continue
                evidence = list(previous.evidence)
                by_chunk = {item.chunk_id: item for item in evidence}
                for item in candidate.evidence:
                    existing = by_chunk.get(item.chunk_id)
                    if existing is not None:
                        if existing.document_id != item.document_id or existing.pokemon_id != item.pokemon_id:
                            raise RetrievalUnavailableError("retrieval branches disagree on chunk lineage")
                        continue
                    if len(evidence) < 3:
                        evidence.append(item)
                        by_chunk[item.chunk_id] = item
                merged[candidate.pokemon_id] = replace(previous, evidence=tuple(evidence))
        return list(merged.values())

    def recommend(self, user_text: str, top_k: int = 3, *, mbti: str | None = None) -> list[dict[str, Any]]:
        text = str(user_text).strip()
        if not text:
            raise ValueError("使用者輸入不可為空。")
        if not 1 <= top_k <= 10:
            raise ValueError("top_k 必須介於 1 到 10。")
        selected_mbti = self._selected_mbti(mbti)
        try:
            scorer = (self.mbti_provider.scorer(self.profile_engine.st_model, self.embedding_model_key, self._encode_lock)
                      if self.mbti_provider is not None else self.mbti_scorer)
        except Exception:
            raise RetrievalUnavailableError("MBTI catalog is temporarily unavailable") from None
        catalog = scorer.catalog
        profile_engine, row_indexes = self._profile_state
        try:
            with self._encode_lock:
                encoded = profile_engine.st_model.encode(text, normalize_embeddings=True)
            query_vector = normalized_embedding(encoded)
            user_affinity = scorer.affinity(text, query_vector)
        except Exception:
            raise RetrievalUnavailableError("query encoder is temporarily unavailable") from None

        try:
            with self.session_factory() as session:
                # Configure before the first SELECT. PostgreSQL also enforces
                # read-only access for this consistent request snapshot.
                session.connection(execution_options={
                    "isolation_level": "REPEATABLE READ", "postgresql_readonly": True,
                })
                retriever = self._retrieval_service_factory(session)
                text_candidates = retriever.retrieve(
                    query_text=text, query_vector=query_vector.tolist(),
                    embedding_model_id=self.embedding_model_id, pokemon_limit=50,
                )
                mbti_candidates = []
                selected_profile = None
                if selected_mbti is not None:
                    selected_profile = catalog.profile_for(selected_mbti)
                    mbti_candidates = retriever.retrieve(
                        query_text=selected_profile.matching_text,
                        query_vector=scorer.prototype_vectors[catalog.codes.index(selected_mbti)].tolist(),
                        embedding_model_id=self.embedding_model_id, pokemon_limit=50,
                    )
                candidates = self._union_candidates(text_candidates, mbti_candidates)
                indexed_profiles = self._mbti_profile_repository_factory(session).load_profiles(
                    [candidate.pokemon_id for candidate in candidates],
                    embedding_model_id=self.embedding_model_id,
                )
        except RetrievalUnavailableError:
            raise
        except Exception:
            raise RetrievalUnavailableError("hybrid retrieval is temporarily unavailable") from None

        if any(candidate.pokemon_id not in row_indexes for candidate in candidates):
            try:
                self.refresh_profiles()
                profile_engine, row_indexes = self._profile_state
            except Exception:
                raise RetrievalUnavailableError("runtime Pokémon profile snapshot is stale") from None

        selected_reference = None
        if selected_profile is not None:
            selected_reference = {
                "code": selected_profile.code, "name_zh": selected_profile.name_zh,
                "summary": selected_profile.summary,
                "information_style": selected_profile.information_style,
                "decision_style": selected_profile.decision_style,
                "interaction_style": selected_profile.interaction_style,
                "action_style": selected_profile.action_style,
                "strengths": list(selected_profile.strengths),
            }
        ranked = []
        max_rrf_score = 2.0 / (RRF_K + 1)
        for candidate in candidates:
            row_index = row_indexes.get(candidate.pokemon_id)
            if row_index is None:
                raise RetrievalUnavailableError("runtime Pokémon profile snapshot is stale")
            row = profile_engine.df.iloc[row_index]
            indexed = indexed_profiles.get(candidate.pokemon_id)
            try:
                pokemon_affinity = (
                    scorer.affinity(indexed.text, indexed.embedding)
                    if indexed is not None else np.zeros(16)
                )
                scores = scorer.score_components(
                    candidate.retrieval_score / max_rrf_score, user_affinity,
                    pokemon_affinity, mbti=selected_mbti,
                )
            except Exception:
                raise RetrievalUnavailableError("personality scoring is temporarily unavailable") from None
            evidence_rows = [
                {
                    "evidence_id": f"ev_{item.chunk_id.hex}",
                    "document_id": str(item.document_id), "chunk_id": str(item.chunk_id),
                    "source": item.source_key, "document_kind": item.document_kind,
                    "language_code": item.language_code, "text": item.content[:240],
                    "content_hash": item.content_hash,
                    "dense_rank": item.dense_rank,
                    "dense_score": round(float(np.clip(item.dense_score, -1, 1)), 8) if item.dense_score is not None else None,
                    "lexical_rank": item.lexical_rank,
                    "lexical_score": round(max(0.0, item.lexical_score), 8) if item.lexical_score is not None else None,
                    "rrf_score": round(item.rrf_score, 10),
                    "matched_traits": scorer.matched_terms(item.content[:240]),
                }
                for item in candidate.evidence
            ]
            allowed_text = "\n".join(item["text"] for item in evidence_rows)
            chinese_text = "\n".join(
                item["text"] for item in evidence_rows
                if item["language_code"].casefold().startswith("zh") or item["source"] == "description_zh"
            )
            pokedex_value = row[profile_engine.id_col]
            pokedex_number = int(pokedex_value) if str(pokedex_value).isdigit() else pokedex_value
            result = {
                "database_id": candidate.pokemon_id, "pokedex_number": pokedex_number,
                "name": profile_engine.safe_get(row, profile_engine.name_col),
                "name_en": profile_engine.safe_get(row, profile_engine.name_en_col),
                "type": profile_engine.safe_get(row, profile_engine.type_col),
                "type_en": ", ".join(str(profile_engine.safe_get(row, column)) for column in (profile_engine.type_1_col, profile_engine.type_2_col)).strip(", "),
                "category": profile_engine.safe_get(row, profile_engine.cat_col),
                "genus": profile_engine.safe_get(row, profile_engine.genus_col),
                "desc": chinese_text,
                "flavor_text_en": "\n".join(item["text"] for item in evidence_rows if item["language_code"] == "en"),
                "analysis_text": allowed_text,
                "img": profile_engine.safe_get(row, profile_engine.img_col) or profile_engine.safe_get(row, profile_engine.sprite_col),
                "scores": scores, "matching_evidence": evidence_rows,
                "selected_mbti": selected_mbti, "mbti_profile": selected_reference,
                "user_traits": scorer.matched_terms(text),
                "pokemon_traits": scorer.matched_terms(allowed_text),
            }
            ranked.append((
                (-scores["total"], -scores["semantic"], -scores["personality"],
                 int(pokedex_number), str(row.get("_form_key", "default")), candidate.pokemon_id),
                result,
            ))
        ranked.sort(key=lambda item: item[0])
        ordered = [item[1] for item in ranked]
        if self.reranker is not None:
            rerank_limit = min(len(ordered), self.reranker.config.candidate_limit)
            outcome = self.reranker.rerank(text, ordered[:rerank_limit])
            if outcome.applied:
                ordered = list(outcome.candidates) + ordered[rerank_limit:]
        selected = ordered[:top_k]
        if len(selected) != top_k:
            raise RetrievalUnavailableError(
                f"hybrid index returned only {len(selected)} unique Pokémon"
            )
        results: list[dict[str, Any]] = []
        for rank, result in enumerate(selected, start=1):
            result["rank"] = rank
            results.append(result)
        return results

    def explain_results(self, user_text: str, pokemon_results: list[dict[str, Any]]) -> dict[int, dict[str, object]]:
        explanations = self.explanation_service.explain_many(user_text, pokemon_results)
        return {pokemon_id: explanation.as_dict() for pokemon_id, explanation in explanations.items()}

    def explain(self, user_text: str, pokemon: dict[str, Any]) -> dict[str, object]:
        return self.explain_results(user_text, [pokemon])[int(pokemon["database_id"])]
