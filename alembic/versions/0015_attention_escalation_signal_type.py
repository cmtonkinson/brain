"""Add signal type to escalation logs.

Revision ID: 0015_attention_escalation_signal_type
Revises: 0014_attention_decision_records
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0015_attention_escalation_signal_type"
down_revision = "0014_attention_decision_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add signal_type column and index to attention escalation logs."""
    op.add_column(
        "attention_escalation_logs",
        sa.Column("signal_type", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "ix_attention_escalation_owner_type_ts",
        "attention_escalation_logs",
        ["owner", "signal_type", "timestamp"],
        unique=False,
    )


def downgrade() -> None:
    """Remove signal_type column and index from attention escalation logs."""
    op.drop_index(
        "ix_attention_escalation_owner_type_ts",
        table_name="attention_escalation_logs",
    )
    op.drop_column("attention_escalation_logs", "signal_type")
