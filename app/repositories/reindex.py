"""Stage and atomically activate versioned knowledge indexes."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    Pokemon,
    PokemonChunkEmbedding,
    PokemonDescription,
    PokemonKnowledgeChunk,
    PokemonKnowledgeDocument,
)
from app.repositories.vector import EmbeddingCandidate
from app.services.knowledge import build_source_document, split_knowledge_document


DOCUMENT_KIND_BY_SOURCE = {
    "description_zh": "description_zh",
    "flavor_text_en": "flavor_text_en",
    "analysis_text": "analysis_text",
}


@dataclass(frozen=True)
class IndexSourceState:
    source_key: str
    status: str
    current_document_id: UUID | None
    current_version: int | None
    staged_document_id: UUID | None
    staged_version: int | None
    total_chunks: int
    ready_chunks: int
    last_error: str | None


@dataclass(frozen=True)
class PokemonIndexState:
    pokemon_id: int
    status: str
    sources: tuple[IndexSourceState, ...]


def normalized_source_key(description: PokemonDescription) -> str:
    return description.source_key.removeprefix("csv:")


class PokemonReindexRepository:
    """Keep a serving index current until its replacement is fully embedded."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_pokemon(self, pokemon_id: int) -> Pokemon | None:
        statement = (
            select(Pokemon)
            .where(Pokemon.id == pokemon_id)
            .options(
                selectinload(Pokemon.descriptions),
                selectinload(Pokemon.knowledge_documents)
                .selectinload(PokemonKnowledgeDocument.chunks)
                .selectinload(PokemonKnowledgeChunk.embeddings),
            )
            .execution_options(populate_existing=True)
        )
        return self.session.scalar(statement)

    def stage_description_sources(
        self,
        pokemon: Pokemon,
        source_keys: set[str] | None = None,
    ) -> int:
        """Create non-serving document versions for changed editable sources."""

        self.session.flush()
        requested = (
            {value.removeprefix("csv:") for value in source_keys}
            if source_keys is not None
            else None
        )
        staged = 0
        for description in pokemon.descriptions:
            source_key = normalized_source_key(description)
            if requested is not None and source_key not in requested:
                continue
            documents = [
                item
                for item in pokemon.knowledge_documents
                if item.source_key == source_key
            ]
            current = next((item for item in documents if item.is_current), None)
            if current is not None and current.content_hash == description.content_hash:
                continue
            latest = max(documents, key=lambda item: item.version, default=None)
            if (
                latest is not None
                and not latest.is_current
                and latest.content_hash == description.content_hash
            ):
                continue

            version = max((item.version for item in documents), default=0) + 1
            document = build_source_document(
                pokemon_key=f"{pokemon.pokedex_number}:{pokemon.form_key}",
                source_key=source_key,
                document_kind=DOCUMENT_KIND_BY_SOURCE.get(
                    source_key,
                    description.description_kind,
                ),
                language=description.language_code,
                content=description.content,
                version=version,
            )
            row = PokemonKnowledgeDocument(
                id=UUID(document.document_id),
                source_description=description,
                source_key=document.source_key,
                document_kind=document.document_kind,
                language_code=document.language,
                content=document.content,
                content_hash=document.content_hash,
                version=document.version,
                is_current=False,
                status="stale",
            )
            row.chunks = [
                PokemonKnowledgeChunk(
                    id=UUID(chunk.chunk_id),
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    lexical_text=chunk.lexical_text,
                    content_hash=chunk.content_hash,
                    char_count=chunk.char_count,
                    token_count=chunk.token_count,
                    is_current=False,
                    status="stale",
                )
                for chunk in split_knowledge_document(document)
            ]
            pokemon.knowledge_documents.append(row)
            staged += 1
        self.session.flush()
        return staged

    @staticmethod
    def matching_staged_documents(
        pokemon: Pokemon,
    ) -> list[PokemonKnowledgeDocument]:
        desired_hashes = {
            normalized_source_key(item): item.content_hash
            for item in pokemon.descriptions
        }
        latest: dict[str, PokemonKnowledgeDocument] = {}
        for document in sorted(
            pokemon.knowledge_documents,
            key=lambda item: (item.source_key, -item.version),
        ):
            if document.is_current or document.source_key in latest:
                continue
            if desired_hashes.get(document.source_key) == document.content_hash:
                latest[document.source_key] = document
        return [latest[key] for key in sorted(latest)]

    @staticmethod
    def removed_current_documents(
        pokemon: Pokemon,
    ) -> list[PokemonKnowledgeDocument]:
        desired_sources = {
            normalized_source_key(item) for item in pokemon.descriptions
        }
        return [
            document
            for document in pokemon.knowledge_documents
            if document.is_current
            and document.source_key != "profile"
            and document.source_key not in desired_sources
        ]

    def pending_chunks(
        self,
        document_id: UUID,
        embedding_model_id: int,
    ) -> list[EmbeddingCandidate]:
        statement = (
            select(
                PokemonKnowledgeChunk.id,
                PokemonKnowledgeChunk.content,
                PokemonKnowledgeChunk.content_hash,
                PokemonChunkEmbedding.status,
                PokemonChunkEmbedding.embedding,
                PokemonChunkEmbedding.content_hash,
            )
            .outerjoin(
                PokemonChunkEmbedding,
                and_(
                    PokemonChunkEmbedding.chunk_id == PokemonKnowledgeChunk.id,
                    PokemonChunkEmbedding.embedding_model_id == embedding_model_id,
                ),
            )
            .where(PokemonKnowledgeChunk.document_id == document_id)
            .order_by(PokemonKnowledgeChunk.chunk_index, PokemonKnowledgeChunk.id)
        )
        return [
            EmbeddingCandidate(row[0], row[1], row[2])
            for row in self.session.execute(statement)
            if row[3] != "ready" or row[4] is None or row[5] != row[2]
        ]

    def document_is_ready(
        self,
        document_id: UUID,
        embedding_model_id: int,
    ) -> bool:
        total, ready, _failed, _error = self._embedding_state(
            document_id,
            embedding_model_id,
        )
        return total > 0 and ready == total

    def retry_document(self, document: PokemonKnowledgeDocument) -> None:
        document.status = "stale"
        for chunk in document.chunks:
            chunk.status = "stale"

    def fail_document(
        self,
        document: PokemonKnowledgeDocument,
    ) -> None:
        document.status = "failed"
        document.is_current = False
        for chunk in document.chunks:
            chunk.status = "failed"
            chunk.is_current = False
        self.session.flush()

    def activate_document(
        self,
        pokemon: Pokemon,
        document: PokemonKnowledgeDocument,
    ) -> None:
        """Switch versions inside one transaction after every vector is ready."""

        for old in pokemon.knowledge_documents:
            if (
                old.source_key == document.source_key
                and old.id != document.id
                and old.is_current
            ):
                old.is_current = False
                old.status = "stale"
                for chunk in old.chunks:
                    chunk.is_current = False
                    chunk.status = "stale"
        self.session.flush()
        document.is_current = True
        document.status = "ready"
        for chunk in document.chunks:
            chunk.is_current = True
            chunk.status = "ready"
        self.session.flush()

    def retire_document(self, document: PokemonKnowledgeDocument) -> None:
        document.is_current = False
        document.status = "stale"
        for chunk in document.chunks:
            chunk.is_current = False
            chunk.status = "stale"
        self.session.flush()

    def index_state(
        self,
        pokemon: Pokemon,
        embedding_model_id: int | None,
    ) -> PokemonIndexState:
        descriptions = {
            normalized_source_key(item): item for item in pokemon.descriptions
        }
        current = {
            item.source_key: item
            for item in pokemon.knowledge_documents
            if item.is_current
        }
        staged = {
            item.source_key: item
            for item in self.matching_staged_documents(pokemon)
        }
        source_keys = set(descriptions) | set(current) | set(staged)
        states: list[IndexSourceState] = []
        for source_key in sorted(source_keys):
            current_document = current.get(source_key)
            staged_document = staged.get(source_key)
            description = descriptions.get(source_key)
            current_matches = current_document is not None and (
                source_key == "profile"
                or (
                    description is not None
                    and current_document.content_hash == description.content_hash
                )
            )
            target = current_document if current_matches else staged_document
            total = ready = failed = 0
            last_error = None
            if target is not None and embedding_model_id is not None:
                total, ready, failed, last_error = self._embedding_state(
                    target.id,
                    embedding_model_id,
                )

            if current_matches and total > 0 and ready == total:
                status = "ready"
            elif target is not None and (target.status == "failed" or failed > 0):
                status = "failed"
            elif target is not None or current_document is not None:
                status = "stale"
            else:
                status = "unindexed"
            states.append(
                IndexSourceState(
                    source_key=source_key,
                    status=status,
                    current_document_id=(
                        current_document.id if current_document is not None else None
                    ),
                    current_version=(
                        current_document.version if current_document is not None else None
                    ),
                    staged_document_id=(
                        staged_document.id if staged_document is not None else None
                    ),
                    staged_version=(
                        staged_document.version if staged_document is not None else None
                    ),
                    total_chunks=total,
                    ready_chunks=ready,
                    last_error=last_error,
                )
            )

        statuses = {item.status for item in states}
        if "failed" in statuses:
            overall = "failed"
        elif statuses & {"stale", "unindexed"}:
            overall = "stale" if states else "unindexed"
        elif states:
            overall = "ready"
        else:
            overall = "unindexed"
        return PokemonIndexState(
            pokemon_id=pokemon.id,
            status=overall,
            sources=tuple(states),
        )

    def _embedding_state(
        self,
        document_id: UUID,
        embedding_model_id: int,
    ) -> tuple[int, int, int, str | None]:
        statement = (
            select(
                PokemonKnowledgeChunk.content_hash,
                PokemonChunkEmbedding.status,
                PokemonChunkEmbedding.embedding,
                PokemonChunkEmbedding.content_hash,
                PokemonChunkEmbedding.last_error,
            )
            .outerjoin(
                PokemonChunkEmbedding,
                and_(
                    PokemonChunkEmbedding.chunk_id == PokemonKnowledgeChunk.id,
                    PokemonChunkEmbedding.embedding_model_id == embedding_model_id,
                ),
            )
            .where(PokemonKnowledgeChunk.document_id == document_id)
        )
        rows = list(self.session.execute(statement))
        ready = sum(
            row[1] == "ready" and row[2] is not None and row[3] == row[0]
            for row in rows
        )
        failed_rows = [row for row in rows if row[1] == "failed"]
        last_error = next(
            (row[4] for row in reversed(failed_rows) if row[4]),
            None,
        )
        return len(rows), ready, len(failed_rows), last_error
