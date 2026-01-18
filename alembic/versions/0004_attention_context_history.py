"""Add attention context and notification history tables.

Revision ID: 0004_attention_context_history
Revises: 0003_notification_envelopes
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_attention_context_history"
down_revision = "0003_notification_envelopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create attention context and notification history tables."""
    op.create_table(
        "attention_context_windows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interruptible", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_attention_context_owner_time",
        "attention_context_windows",
        ["owner", "start_at", "end_at"],
        unique=False,
    )
    op.create_table(
        "notification_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("signal_reference", sa.String(length=500), nullable=False),
        sa.Column("outcome", sa.String(length=50), nullable=False),
        sa.Column("channel", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_notification_history_owner_time",
        "notification_history",
        ["owner", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_notification_history_owner_channel_outcome",
        "notification_history",
        ["owner", "channel", "outcome"],
        unique=False,
    )


def downgrade() -> None:
    """Drop attention context and notification history tables."""
    op.drop_index(
        "ix_notification_history_owner_channel_outcome", table_name="notification_history"
    )
    op.drop_index("ix_notification_history_owner_time", table_name="notification_history")
    op.drop_table("notification_history")
    op.drop_index("ix_attention_context_owner_time", table_name="attention_context_windows")
    op.drop_table("attention_context_windows")
