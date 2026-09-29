"""Add privacy-safe recommendation impressions and bounded feedback.

Revision ID: 20260929_0010
Revises: 20260929_0009
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260929_0010"
down_revision: str | None = "20260929_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recommendation_impressions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("algorithm_version", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "length(trim(algorithm_version)) > 0",
            name="ck_recommendation_impressions_algorithm_version_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recommendation_impressions"),
    )
    op.create_index(
        "ix_recommendation_impressions_created",
        "recommendation_impressions",
        ["created_at", "id"],
    )

    op.create_table(
        "recommendation_impression_items",
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("pokemon_id", sa.BigInteger(), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "rank BETWEEN 1 AND 3",
            name="ck_recommendation_impression_items_rank_range",
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["recommendation_impressions.id"],
            name="fk_rec_items_recommendation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pokemon_id"],
            ["pokemon.id"],
            name="fk_recommendation_impression_items_pokemon_id_pokemon",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "recommendation_id",
            "pokemon_id",
            name="pk_recommendation_impression_items",
        ),
        sa.UniqueConstraint(
            "recommendation_id",
            "rank",
            name="uq_recommendation_impression_items_rank",
        ),
    )

    op.create_table(
        "recommendation_feedback",
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("pokemon_id", sa.BigInteger(), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(32), server_default="no_reason", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "verdict IN ('match', 'not_match')",
            name="ck_recommendation_feedback_verdict_valid",
        ),
        sa.CheckConstraint(
            "reason IN ('no_reason', 'personality_mismatch', 'ranking', 'unfamiliar')",
            name="ck_recommendation_feedback_reason_valid",
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id", "pokemon_id"],
            [
                "recommendation_impression_items.recommendation_id",
                "recommendation_impression_items.pokemon_id",
            ],
            name="fk_recommendation_feedback_impression_item",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "recommendation_id",
            "pokemon_id",
            name="pk_recommendation_feedback",
        ),
    )
    op.create_index(
        "ix_recommendation_feedback_updated",
        "recommendation_feedback",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recommendation_feedback_updated",
        table_name="recommendation_feedback",
    )
    op.drop_table("recommendation_feedback")
    op.drop_table("recommendation_impression_items")
    op.drop_index(
        "ix_recommendation_impressions_created",
        table_name="recommendation_impressions",
    )
    op.drop_table("recommendation_impressions")
