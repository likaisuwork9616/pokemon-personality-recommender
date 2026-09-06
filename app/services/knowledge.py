"""Build traceable Pokémon knowledge documents and retrieval chunks."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

import jieba


DOCUMENT_FIELDS = (
    ("description_zh", "zh-Hant", "description_zh"),
    ("flavor_text_en", "en", "flavor_text_en"),
    ("analysis_text", "mul", "analysis_text"),
)


def content_hash(content: str) -> str:
    """Return the stable SHA-256 identifier used for incremental indexing."""

    return sha256(content.strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    pokemon_key: str
    source_key: str
    document_kind: str
    language: str
    content: str
    content_hash: str
    version: int = 1


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    document_id: str
    chunk_index: int
    content: str
    lexical_text: str
    content_hash: str
    char_count: int
    token_count: int


def _stable_id(kind: str, *parts: object) -> str:
    value = ":".join([kind, *(str(part) for part in parts)])
    return str(uuid5(NAMESPACE_URL, value))


def build_knowledge_documents(
    record: Mapping[str, object],
    *,
    versions: Mapping[str, int] | None = None,
) -> list[KnowledgeDocument]:
    """Convert one imported Pokémon record into independently traceable documents."""

    pokemon_key = f"{record['pokedex_number']}:{record.get('form_key') or 'default'}"
    version_by_source = versions or {}
    documents: list[KnowledgeDocument] = []

    profile_parts = [
        f"中文名稱：{record.get('name_zh', '')}",
        f"English name: {record.get('name_en', '')}",
        f"屬性：{record.get('type_zh', '')}",
        f"分類：{record.get('category_zh', '')}",
        f"世代：{record.get('generation', '')}",
        f"棲地：{record.get('habitat', '')}",
        f"特性：{record.get('abilities', '')}",
    ]
    profile = "\n".join(part for part in profile_parts if part.split("：", 1)[-1].strip())
    sources = [("profile", "mixed", "profile", profile)]
    sources.extend(
        (kind, language, source_key, str(record.get(field, "") or "").strip())
        for kind, language, field in DOCUMENT_FIELDS
        for source_key in [field]
    )

    for document_kind, language, source_key, content in sources:
        if not content:
            continue
        version = version_by_source.get(source_key, 1)
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError(f"version for {source_key!r} must be a positive integer")
        digest = content_hash(content)
        documents.append(
            KnowledgeDocument(
                document_id=_stable_id(
                    "document",
                    pokemon_key,
                    source_key,
                    version,
                    digest,
                ),
                pokemon_key=pokemon_key,
                source_key=source_key,
                document_kind=document_kind,
                language=language,
                content=content,
                content_hash=digest,
                version=version,
            )
        )
    return documents


def _sentences(content: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n+", content) if part.strip()]
    sentences: list[str] = []
    for paragraph in paragraphs:
        sentences.extend(
            part.strip()
            for part in re.split(r"(?<=[。！？!?；;\.])\s*", paragraph)
            if part.strip()
        )
    return sentences


def _windowed_chunks(sentences: Iterable[str], max_chars: int, overlap_chars: int) -> list[str]:
    """Pack sentences into bounded windows with deterministic character overlap."""

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            candidate = sentence
        else:
            candidate = f"{current} {sentence}"

        if current and len(candidate) > max_chars:
            chunks.append(current)
            overlap = current[-overlap_chars:] if overlap_chars else ""
            candidate = f"{overlap} {sentence}" if overlap else sentence

        step = max_chars - overlap_chars
        while len(candidate) > max_chars:
            chunks.append(candidate[:max_chars])
            candidate = candidate[step:]
        current = candidate

    if current:
        chunks.append(current)
    return chunks


def split_knowledge_document(
    document: KnowledgeDocument,
    *,
    max_chars: int = 500,
    overlap_chars: int = 80,
) -> list[KnowledgeChunk]:
    """Split a document while preserving deterministic lineage metadata."""

    if max_chars < 100:
        raise ValueError("max_chars must be at least 100")
    if not 0 <= overlap_chars < max_chars:
        raise ValueError("overlap_chars must be between 0 and max_chars")

    chunks: list[KnowledgeChunk] = []
    for index, text in enumerate(
        _windowed_chunks(_sentences(document.content), max_chars, overlap_chars)
    ):
        digest = content_hash(text)
        tokens = [token.strip() for token in jieba.lcut(text) if token.strip()]
        chunks.append(
            KnowledgeChunk(
                chunk_id=_stable_id("chunk", document.document_id, index, digest),
                document_id=document.document_id,
                chunk_index=index,
                content=text,
                lexical_text=" ".join(tokens),
                content_hash=digest,
                char_count=len(text),
                token_count=len(tokens),
            )
        )
    return chunks
