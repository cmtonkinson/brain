"""Add fail-closed queue for routing recovery.

Revision ID: 0013_attention_fail_closed_queue
Revises: 0012_attention_review_logs
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0013_attention_fail_closed_queue"
down_revision = "0012_attention_review_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create fail-closed queue table."""
    op.create_table(
        "attention_fail_closed_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("source_component", sa.String(length=200), nullable=False),
        sa.Column("from_number", sa.String(length=200), nullable=False),
        sa.Column("to_number", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_fail_closed_owner_retry",
        "attention_fail_closed_queue",
        ["owner", "retry_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop fail-closed queue table."""
    op.drop_index("ix_fail_closed_owner_retry", table_name="attention_fail_closed_queue")
    op.drop_table("attention_fail_closed_queue")
