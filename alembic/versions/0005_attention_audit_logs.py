"""Add attention audit log table.

Revision ID: 0005_attention_audit_logs
Revises: 0004_attention_context_history
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_attention_audit_logs"
down_revision = "0004_attention_context_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create attention audit log table."""
    op.create_table(
        "attention_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_component", sa.String(length=200), nullable=False),
        sa.Column("signal_reference", sa.String(length=500), nullable=False),
        sa.Column("base_assessment", sa.String(length=50), nullable=False),
        sa.Column("policy_outcome", sa.String(length=100), nullable=True),
        sa.Column("final_decision", sa.String(length=100), nullable=False),
        sa.Column("envelope_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["envelope_id"], ["notification_envelopes.id"]),
    )
    op.create_index(
        "ix_attention_audit_log_timestamp",
        "attention_audit_logs",
        ["timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_attention_audit_log_signal",
        "attention_audit_logs",
        ["signal_reference"],
        unique=False,
    )


def downgrade() -> None:
    """Drop attention audit log table."""
    op.drop_index("ix_attention_audit_log_signal", table_name="attention_audit_logs")
    op.drop_index("ix_attention_audit_log_timestamp", table_name="attention_audit_logs")
    op.drop_table("attention_audit_logs")
