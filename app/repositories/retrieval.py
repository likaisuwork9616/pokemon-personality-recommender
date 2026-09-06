"""PostgreSQL full-text retrieval over jieba-tokenized knowledge chunks."""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from uuid import UUID

from sqlalchemy import bindparam, func, literal_column, select
from sqlalchemy.orm import Session

from app.db.models import Pokemon, PokemonKnowledgeChunk, PokemonKnowledgeDocument


@dataclass(frozen=True)
class LexicalSearchHit:
    rank: int
    pokemon_id: int
    document_id: UUID
    chunk_id: UUID
    source_key: str
    document_kind: str
    language_code: str
    content: str
    content_hash: str
    lexical_score: float


class RetrievalRepository:
    """Run parameterized lexical retrieval against the generated tsvector."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def lexical_search(
        self,
        *,
        tokens: tuple[str, ...],
        limit: int = 50,
    ) -> list[LexicalSearchHit]:
        if not tokens:
            return []
        if len(tokens) > 32 or any(not token.strip() for token in tokens):
            raise ValueError("tokens must contain between 1 and 32 non-blank values")
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")

        simple_config = literal_column("'simple'::regconfig")
        token_queries = [
            func.plainto_tsquery(
                simple_config,
                bindparam(f"lexical_token_{index}", value=token),
            )
            for index, token in enumerate(tokens)
        ]
        tsquery = reduce(lambda left, right: left.op("||")(right), token_queries)
        lexical_score = func.ts_rank_cd(
            PokemonKnowledgeChunk.textsearch,
            tsquery,
            32,
        )
        statement = (
            select(
                Pokemon.id,
                PokemonKnowledgeDocument.id,
                PokemonKnowledgeChunk.id,
                PokemonKnowledgeDocument.source_key,
                PokemonKnowledgeDocument.document_kind,
                PokemonKnowledgeDocument.language_code,
                PokemonKnowledgeChunk.content,
                PokemonKnowledgeChunk.content_hash,
                lexical_score.label("lexical_score"),
            )
            .select_from(PokemonKnowledgeChunk)
            .join(PokemonKnowledgeDocument)
            .join(Pokemon)
            .where(
                PokemonKnowledgeChunk.textsearch.op("@@")(tsquery),
                PokemonKnowledgeChunk.is_current.is_(True),
                PokemonKnowledgeChunk.status == "ready",
                PokemonKnowledgeDocument.is_current.is_(True),
                PokemonKnowledgeDocument.status == "ready",
                Pokemon.is_active.is_(True),
            )
            .order_by(lexical_score.desc(), PokemonKnowledgeChunk.id)
            .limit(limit)
        )
        return [
            LexicalSearchHit(
                rank=rank,
                pokemon_id=int(row[0]),
                document_id=row[1],
                chunk_id=row[2],
                source_key=row[3],
                document_kind=row[4],
                language_code=row[5],
                content=row[6],
                content_hash=row[7],
                lexical_score=float(row[8]),
            )
            for rank, row in enumerate(self.session.execute(statement), start=1)
        ]
