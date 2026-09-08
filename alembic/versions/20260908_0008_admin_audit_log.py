"""Add append-only administration audit logs.

Revision ID: 20260908_0008
Revises: 20260907_0007
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260908_0008"
down_revision: str | None = "20260907_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("actor_username", sa.String(64), nullable=False),
        sa.Column("actor_role", sa.String(16), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("resource_type", sa.String(40), nullable=False),
        sa.Column("resource_id", sa.String(120), nullable=True),
        sa.Column("outcome", sa.String(16), server_default="succeeded", nullable=False),
        sa.Column("request_id", sa.String(32), nullable=False),
        sa.Column("http_method", sa.String(10), nullable=False),
        sa.Column("route", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "actor_role IN ('viewer', 'editor', 'admin')",
            name="ck_admin_audit_logs_actor_role_valid",
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'noop')",
            name="ck_admin_audit_logs_outcome_valid",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_audit_logs"),
    )
    op.create_index(
        "ix_admin_audit_logs_created",
        "admin_audit_logs",
        ["created_at", "id"],
    )
    op.create_index(
        "ix_admin_audit_logs_actor",
        "admin_audit_logs",
        ["actor_username", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_admin_audit_logs_actor", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_created", table_name="admin_audit_logs")
    op.drop_table("admin_audit_logs")
