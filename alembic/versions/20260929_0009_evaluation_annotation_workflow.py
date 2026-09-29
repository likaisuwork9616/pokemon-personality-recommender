"""Add collaborative evaluation annotation and adjudication tables.

Revision ID: 20260929_0009
Revises: 20260908_0008
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260929_0009"
down_revision: str | None = "20260908_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_key", sa.String(80), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("segment", sa.String(80), nullable=False),
        sa.Column("dataset_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name="ck_evaluation_cases_status_valid",
        ),
        sa.CheckConstraint(
            "length(trim(case_key)) > 0",
            name="ck_evaluation_cases_case_key_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(query_text)) > 0",
            name="ck_evaluation_cases_query_text_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(segment)) > 0",
            name="ck_evaluation_cases_segment_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(dataset_version)) > 0",
            name="ck_evaluation_cases_dataset_version_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_cases"),
        sa.UniqueConstraint("case_key", name="uq_evaluation_cases_case_key"),
    )
    op.create_index(
        "ix_evaluation_cases_status_version",
        "evaluation_cases",
        ["status", "dataset_version"],
    )

    op.create_table(
        "evaluation_candidates",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("pokemon_id", sa.BigInteger(), nullable=False),
        sa.Column("display_order", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "display_order > 0",
            name="ck_evaluation_candidates_display_order_positive",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["evaluation_cases.id"],
            name="fk_evaluation_candidates_case_id_evaluation_cases",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pokemon_id"],
            ["pokemon.id"],
            name="fk_evaluation_candidates_pokemon_id_pokemon",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "case_id", "pokemon_id", name="pk_evaluation_candidates"
        ),
        sa.UniqueConstraint(
            "case_id",
            "display_order",
            name="uq_evaluation_candidates_case_order",
        ),
    )

    op.create_table(
        "evaluation_annotations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("pokemon_id", sa.BigInteger(), nullable=False),
        sa.Column("annotator_username", sa.String(64), nullable=False),
        sa.Column("grade", sa.SmallInteger(), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "grade BETWEEN 0 AND 3",
            name="ck_evaluation_annotations_grade_range",
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "pokemon_id"],
            ["evaluation_candidates.case_id", "evaluation_candidates.pokemon_id"],
            name="fk_evaluation_annotation_candidate",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_annotations"),
        sa.UniqueConstraint(
            "case_id",
            "pokemon_id",
            "annotator_username",
            name="uq_evaluation_annotations_judgment",
        ),
    )
    op.create_index(
        "ix_evaluation_annotations_annotator",
        "evaluation_annotations",
        ["annotator_username", "case_id"],
    )

    op.create_table(
        "evaluation_adjudications",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("pokemon_id", sa.BigInteger(), nullable=False),
        sa.Column("grade", sa.SmallInteger(), nullable=False),
        sa.Column("adjudicator_username", sa.String(64), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "grade BETWEEN 0 AND 3",
            name="ck_evaluation_adjudications_grade_range",
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "pokemon_id"],
            ["evaluation_candidates.case_id", "evaluation_candidates.pokemon_id"],
            name="fk_evaluation_adjudication_candidate",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "case_id", "pokemon_id", name="pk_evaluation_adjudications"
        ),
    )


def downgrade() -> None:
    op.drop_table("evaluation_adjudications")
    op.drop_index(
        "ix_evaluation_annotations_annotator",
        table_name="evaluation_annotations",
    )
    op.drop_table("evaluation_annotations")
    op.drop_table("evaluation_candidates")
    op.drop_index(
        "ix_evaluation_cases_status_version",
        table_name="evaluation_cases",
    )
    op.drop_table("evaluation_cases")
