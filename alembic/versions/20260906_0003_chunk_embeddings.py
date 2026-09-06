"""Store versioned 384-dimensional chunk embeddings in pgvector.

Revision ID: 20260906_0003
Revises: 20260906_0002
Create Date: 2026-09-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision: str = "20260906_0003"
down_revision: str | None = "20260906_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create model metadata and exact-search chunk vectors."""

    op.create_table(
        "embedding_models",
        sa.Column("id", sa.SmallInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column(
            "dimensions",
            sa.SmallInteger(),
            server_default=sa.text("384"),
            nullable=False,
        ),
        sa.Column(
            "normalize_embeddings",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "dimensions = 384",
            name="ck_embedding_models_dimensions_384",
        ),
        sa.CheckConstraint(
            "length(trim(model_name)) > 0",
            name="ck_embedding_models_model_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(model_version)) > 0",
            name="ck_embedding_models_model_version_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_embedding_models"),
        sa.UniqueConstraint(
            "model_name",
            "model_version",
            name="uq_embedding_model_identity",
        ),
    )
    op.create_index(
        "uq_embedding_models_single_active",
        "embedding_models",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "pokemon_chunk_embeddings",
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_model_id", sa.SmallInteger(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'ready'"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_pokemon_chunk_embeddings_content_hash_length",
        ),
        sa.CheckConstraint(
            "status <> 'ready' OR (embedding IS NOT NULL AND embedded_at IS NOT NULL)",
            name="ck_pokemon_chunk_embeddings_ready_has_vector",
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'stale', 'failed')",
            name="ck_pokemon_chunk_embeddings_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["pokemon_knowledge_chunks.id"],
            name="fk_chunk_embedding_chunk",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_model_id"],
            ["embedding_models.id"],
            name="fk_chunk_embedding_model",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "chunk_id",
            "embedding_model_id",
            name="pk_pokemon_chunk_embeddings",
        ),
    )
    op.create_index(
        "ix_chunk_embeddings_model_status",
        "pokemon_chunk_embeddings",
        ["embedding_model_id", "status", "chunk_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove vector rows and their model registry."""

    op.drop_index(
        "ix_chunk_embeddings_model_status",
        table_name="pokemon_chunk_embeddings",
    )
    op.drop_table("pokemon_chunk_embeddings")
    op.drop_index(
        "uq_embedding_models_single_active",
        table_name="embedding_models",
    )
    op.drop_table("embedding_models")
