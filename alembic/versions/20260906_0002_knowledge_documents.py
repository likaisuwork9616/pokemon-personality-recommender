"""Persist versioned knowledge documents and retrieval chunks.

Revision ID: 20260906_0002
Revises: 20260906_0001
Create Date: 2026-09-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260906_0002"
down_revision: str | None = "20260906_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create document lineage, bounded chunks, and the Chinese-ready FTS index."""

    op.create_table(
        "pokemon_knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pokemon_id", sa.BigInteger(), nullable=False),
        sa.Column("source_description_id", sa.BigInteger(), nullable=True),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("document_kind", sa.String(length=40), nullable=False),
        sa.Column("language_code", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'ready'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_pokemon_knowledge_documents_content_hash_length",
        ),
        sa.CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_pokemon_knowledge_documents_content_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(document_kind)) > 0",
            name="ck_pokemon_knowledge_documents_document_kind_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(language_code)) > 0",
            name="ck_pokemon_knowledge_documents_language_code_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(source_key)) > 0",
            name="ck_pokemon_knowledge_documents_source_key_not_blank",
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'stale', 'failed')",
            name="ck_pokemon_knowledge_documents_status_valid",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_pokemon_knowledge_documents_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["pokemon_id"],
            ["pokemon.id"],
            name="fk_pokemon_knowledge_documents_pokemon_id_pokemon",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_description_id"],
            ["pokemon_descriptions.id"],
            name="fk_knowledge_document_source_description",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pokemon_knowledge_documents"),
        sa.UniqueConstraint(
            "pokemon_id",
            "source_key",
            "version",
            name="uq_knowledge_document_version",
        ),
    )
    op.create_index(
        "ix_knowledge_documents_pokemon_current",
        "pokemon_knowledge_documents",
        ["pokemon_id", "is_current", "status"],
        unique=False,
    )
    op.create_index(
        "uq_knowledge_documents_current_source",
        "pokemon_knowledge_documents",
        ["pokemon_id", "source_key"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "pokemon_knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "lexical_text",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "textsearch",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', coalesce(lexical_text, ''))",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'ready'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_count > 0",
            name="ck_pokemon_knowledge_chunks_char_count_positive",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_pokemon_knowledge_chunks_chunk_index_nonnegative",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_pokemon_knowledge_chunks_content_hash_length",
        ),
        sa.CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_pokemon_knowledge_chunks_content_not_blank",
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'stale', 'failed')",
            name="ck_pokemon_knowledge_chunks_status_valid",
        ),
        sa.CheckConstraint(
            "token_count >= 0",
            name="ck_pokemon_knowledge_chunks_token_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["pokemon_knowledge_documents.id"],
            name="fk_knowledge_chunk_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pokemon_knowledge_chunks"),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            "content_hash",
            name="uq_knowledge_chunk_version",
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_document_current",
        "pokemon_knowledge_chunks",
        ["document_id", "is_current", "status"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_chunks_textsearch",
        "pokemon_knowledge_chunks",
        ["textsearch"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "uq_knowledge_chunks_current_index",
        "pokemon_knowledge_chunks",
        ["document_id", "chunk_index"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )


def downgrade() -> None:
    """Remove knowledge records without touching the core catalog schema."""

    op.drop_index(
        "uq_knowledge_chunks_current_index",
        table_name="pokemon_knowledge_chunks",
    )
    op.drop_index(
        "ix_knowledge_chunks_textsearch",
        table_name="pokemon_knowledge_chunks",
        postgresql_using="gin",
    )
    op.drop_index(
        "ix_knowledge_chunks_document_current",
        table_name="pokemon_knowledge_chunks",
    )
    op.drop_table("pokemon_knowledge_chunks")

    op.drop_index(
        "uq_knowledge_documents_current_source",
        table_name="pokemon_knowledge_documents",
    )
    op.drop_index(
        "ix_knowledge_documents_pokemon_current",
        table_name="pokemon_knowledge_documents",
    )
    op.drop_table("pokemon_knowledge_documents")
