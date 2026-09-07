"""Version and normalize the administrable personality vocabulary.

Revision ID: 20260907_0007
Revises: 20260907_0006
"""

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "20260907_0007"
down_revision: str | None = "20260907_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("personality_trait_synonyms", sa.Column("normalized_term", sa.String(80), nullable=True))
    op.execute("UPDATE personality_trait_synonyms SET normalized_term = lower(trim(term))")
    op.alter_column("personality_trait_synonyms", "normalized_term", nullable=False)
    op.create_check_constraint(
        "ck_personality_trait_synonyms_normalized_term_not_blank",
        "personality_trait_synonyms",
        "length(trim(normalized_term)) > 0",
    )
    op.create_unique_constraint(
        "uq_personality_synonyms_trait_normalized_term",
        "personality_trait_synonyms",
        ["trait_code", "normalized_term"],
    )
    op.create_table(
        "personality_vocabulary_state",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("revision", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_personality_vocabulary_state_singleton_id"),
        sa.CheckConstraint("revision > 0", name="ck_personality_vocabulary_state_revision_positive"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO personality_vocabulary_state (id, revision) VALUES (1, 1)")


def downgrade() -> None:
    op.drop_table("personality_vocabulary_state")
    op.drop_constraint("uq_personality_synonyms_trait_normalized_term", "personality_trait_synonyms", type_="unique")
    op.drop_constraint("ck_personality_trait_synonyms_normalized_term_not_blank", "personality_trait_synonyms", type_="check")
    op.drop_column("personality_trait_synonyms", "normalized_term")
