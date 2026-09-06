"""Deterministic dense/lexical retrieval fusion without LLM involvement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence
from unicodedata import category
from uuid import UUID

import jieba

from app.repositories.retrieval import LexicalSearchHit
from app.repositories.vector import VectorSearchHit


BRANCH_LIMIT = 50
MAX_QUERY_TOKENS = 32
RRF_K = 60
MAX_CHUNKS_PER_POKEMON = 3


@dataclass(frozen=True)
class FusedChunkHit:
    pokemon_id: int
    document_id: UUID
    chunk_id: UUID
    source_key: str
    document_kind: str
    language_code: str
    content: str
    content_hash: str
    dense_rank: int | None
    dense_score: float | None
    lexical_rank: int | None
    lexical_score: float | None
    rrf_score: float


@dataclass(frozen=True)
class PokemonRetrievalCandidate:
    pokemon_id: int
    retrieval_score: float
    best_chunk_score: float
    best_branch_rank: int
    evidence: tuple[FusedChunkHit, ...]


class DenseRetriever(Protocol):
    def exact_search(
        self,
        *,
        query_vector: Sequence[float],
        embedding_model_id: int,
        limit: int,
    ) -> list[VectorSearchHit]: ...


class LexicalRetriever(Protocol):
    def lexical_search(
        self,
        *,
        tokens: tuple[str, ...],
        limit: int,
    ) -> list[LexicalSearchHit]: ...


def tokenize_lexical_query(text: str, *, max_tokens: int = MAX_QUERY_TOKENS) -> tuple[str, ...]:
    """Tokenize safely, discarding whitespace/punctuation and stable duplicates."""

    if not 1 <= max_tokens <= MAX_QUERY_TOKENS:
        raise ValueError(f"max_tokens must be between 1 and {MAX_QUERY_TOKENS}")
    tokens: list[str] = []
    seen: set[str] = set()
    for raw_token in jieba.lcut(str(text)):
        token = raw_token.strip()
        if not token or not any(category(character)[0] in {"L", "N"} for character in token):
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        tokens.append(token)
        if len(tokens) == max_tokens:
            break
    return tuple(tokens)


class HybridRetrievalService:
    """Fuse branch ranks per chunk, then aggregate a bounded set per Pokémon."""

    def __init__(
        self,
        dense_retriever: DenseRetriever,
        lexical_retriever: LexicalRetriever,
        *,
        rrf_k: int = RRF_K,
        branch_limit: int = BRANCH_LIMIT,
        max_chunks_per_pokemon: int = MAX_CHUNKS_PER_POKEMON,
    ) -> None:
        if rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        if not 1 <= branch_limit <= BRANCH_LIMIT:
            raise ValueError(f"branch_limit must be between 1 and {BRANCH_LIMIT}")
        if not 1 <= max_chunks_per_pokemon <= MAX_CHUNKS_PER_POKEMON:
            raise ValueError(
                "max_chunks_per_pokemon must be between 1 and "
                f"{MAX_CHUNKS_PER_POKEMON}"
            )
        self.dense_retriever = dense_retriever
        self.lexical_retriever = lexical_retriever
        self.rrf_k = rrf_k
        self.branch_limit = branch_limit
        self.max_chunks_per_pokemon = max_chunks_per_pokemon

    def retrieve(
        self,
        *,
        query_text: str,
        query_vector: Sequence[float],
        embedding_model_id: int,
        pokemon_limit: int = 50,
    ) -> list[PokemonRetrievalCandidate]:
        if not 1 <= pokemon_limit <= 100:
            raise ValueError("pokemon_limit must be between 1 and 100")
        dense_hits = self.dense_retriever.exact_search(
            query_vector=query_vector,
            embedding_model_id=embedding_model_id,
            limit=self.branch_limit,
        )
        tokens = tokenize_lexical_query(query_text)
        lexical_hits = (
            self.lexical_retriever.lexical_search(
                tokens=tokens,
                limit=self.branch_limit,
            )
            if tokens
            else []
        )
        chunks = self._fuse_chunks(dense_hits, lexical_hits)
        return self._aggregate_pokemon(chunks)[:pokemon_limit]

    def _fuse_chunks(
        self,
        dense_hits: Sequence[VectorSearchHit],
        lexical_hits: Sequence[LexicalSearchHit],
    ) -> list[FusedChunkHit]:
        combined: dict[UUID, dict[str, object]] = {}
        for hit in dense_hits:
            stored = combined.setdefault(hit.chunk_id, self._base_hit(hit))
            self._validate_lineage(stored, hit)
            dense_rank = stored["dense_rank"]
            if dense_rank is None or hit.rank < dense_rank:
                stored.update(
                    dense_rank=hit.rank,
                    dense_score=hit.semantic_score,
                )
        for hit in lexical_hits:
            stored = combined.setdefault(hit.chunk_id, self._base_hit(hit))
            self._validate_lineage(stored, hit)
            lexical_rank = stored["lexical_rank"]
            if lexical_rank is None or hit.rank < lexical_rank:
                stored.update(
                    lexical_rank=hit.rank,
                    lexical_score=hit.lexical_score,
                )

        fused: list[FusedChunkHit] = []
        for values in combined.values():
            dense_rank = values.get("dense_rank")
            lexical_rank = values.get("lexical_rank")
            score = sum(
                1.0 / (self.rrf_k + rank)
                for rank in (dense_rank, lexical_rank)
                if isinstance(rank, int)
            )
            fused.append(FusedChunkHit(**values, rrf_score=score))
        return sorted(fused, key=self._chunk_sort_key)

    @staticmethod
    def _base_hit(hit) -> dict[str, object]:
        return {
            "pokemon_id": hit.pokemon_id,
            "document_id": hit.document_id,
            "chunk_id": hit.chunk_id,
            "source_key": hit.source_key,
            "document_kind": hit.document_kind,
            "language_code": hit.language_code,
            "content": hit.content,
            "content_hash": hit.content_hash,
            "dense_rank": None,
            "dense_score": None,
            "lexical_rank": None,
            "lexical_score": None,
        }

    @staticmethod
    def _validate_lineage(stored: dict[str, object], hit) -> None:
        if (
            stored["pokemon_id"] != hit.pokemon_id
            or stored["document_id"] != hit.document_id
        ):
            raise ValueError("retrieval branches disagree on chunk lineage")

    @staticmethod
    def _best_branch_rank(hit: FusedChunkHit) -> int:
        ranks = tuple(
            rank
            for rank in (hit.dense_rank, hit.lexical_rank)
            if isinstance(rank, int)
        )
        if not ranks:
            raise ValueError("fused chunk must contain at least one branch rank")
        return min(ranks)

    @staticmethod
    def _chunk_sort_key(hit: FusedChunkHit) -> tuple[float, int, int, str]:
        return (
            -hit.rrf_score,
            HybridRetrievalService._best_branch_rank(hit),
            hit.pokemon_id,
            str(hit.chunk_id),
        )

    def _aggregate_pokemon(
        self,
        chunks: Sequence[FusedChunkHit],
    ) -> list[PokemonRetrievalCandidate]:
        grouped: dict[int, list[FusedChunkHit]] = {}
        for chunk in chunks:
            grouped.setdefault(chunk.pokemon_id, []).append(chunk)

        candidates: list[PokemonRetrievalCandidate] = []
        for pokemon_id, pokemon_chunks in grouped.items():
            evidence = tuple(
                sorted(pokemon_chunks, key=self._chunk_sort_key)[
                    : self.max_chunks_per_pokemon
                ]
            )
            best_score = evidence[0].rrf_score
            best_branch_rank = min(self._best_branch_rank(item) for item in evidence)
            mean_score = sum(item.rrf_score for item in evidence) / len(evidence)
            candidates.append(
                PokemonRetrievalCandidate(
                    pokemon_id=pokemon_id,
                    retrieval_score=0.75 * best_score + 0.25 * mean_score,
                    best_chunk_score=best_score,
                    best_branch_rank=best_branch_rank,
                    evidence=evidence,
                )
            )
        return sorted(
            candidates,
            key=lambda item: (
                -item.retrieval_score,
                -item.best_chunk_score,
                item.best_branch_rank,
                item.pokemon_id,
            ),
        )
