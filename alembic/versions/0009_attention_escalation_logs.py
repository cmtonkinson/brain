"""Add attention escalation log table.

Revision ID: 0009_attention_escalation_logs
Revises: 0008_attention_audit_preference_ref
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009_attention_escalation_logs"
down_revision = "0008_attention_audit_preference_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create attention escalation log table."""
    op.create_table(
        "attention_escalation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("signal_reference", sa.String(length=500), nullable=False),
        sa.Column("trigger", sa.String(length=200), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_attention_escalation_owner_time",
        "attention_escalation_logs",
        ["owner", "timestamp"],
        unique=False,
    )


def downgrade() -> None:
    """Drop attention escalation log table."""
    op.drop_index("ix_attention_escalation_owner_time", table_name="attention_escalation_logs")
    op.drop_table("attention_escalation_logs")
