"""Add attention review logs for suppressed signals.

Revision ID: 0012_attention_review_logs
Revises: 0011_attention_batch_summaries
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012_attention_review_logs"
down_revision = "0011_attention_batch_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create attention review logs table."""
    op.create_table(
        "attention_review_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("signal_reference", sa.String(length=500), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Drop attention review logs table."""
    op.drop_table("attention_review_logs")
