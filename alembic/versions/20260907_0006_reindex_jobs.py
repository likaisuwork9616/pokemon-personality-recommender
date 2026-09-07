"""Add durable PostgreSQL-backed reindex jobs.

Revision ID: 20260907_0006
Revises: 20260907_0005
"""

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "20260907_0006"
down_revision: str | None = "20260907_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pokemon_reindex_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pokemon_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), server_default="queued", nullable=False),
        sa.Column("progress_current", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("embedded", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("message", sa.String(500), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_pokemon_reindex_jobs_status_valid"),
        sa.CheckConstraint("progress_current >= 0", name="ck_pokemon_reindex_jobs_progress_current_nonnegative"),
        sa.CheckConstraint("progress_total >= 0", name="ck_pokemon_reindex_jobs_progress_total_nonnegative"),
        sa.CheckConstraint("embedded >= 0", name="ck_pokemon_reindex_jobs_embedded_nonnegative"),
        sa.CheckConstraint("failed >= 0", name="ck_pokemon_reindex_jobs_failed_nonnegative"),
        sa.ForeignKeyConstraint(["pokemon_id"], ["pokemon.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reindex_jobs_claim", "pokemon_reindex_jobs", ["status", "queued_at", "id"])
    op.create_index(
        "uq_reindex_jobs_one_active_per_pokemon",
        "pokemon_reindex_jobs",
        ["pokemon_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_reindex_jobs_one_active_per_pokemon", table_name="pokemon_reindex_jobs")
    op.drop_index("ix_reindex_jobs_claim", table_name="pokemon_reindex_jobs")
    op.drop_table("pokemon_reindex_jobs")
