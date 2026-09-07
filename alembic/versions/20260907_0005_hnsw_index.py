"""Add an HNSW cosine index for chunk embeddings.

Revision ID: 20260907_0005
Revises: 20260907_0004
Create Date: 2026-09-07
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260907_0005"
down_revision: str | None = "20260907_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_NAME = "ix_chunk_embeddings_embedding_hnsw"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "pokemon_chunk_embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_where=sa.text("status = 'ready' AND embedding IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="pokemon_chunk_embeddings")
