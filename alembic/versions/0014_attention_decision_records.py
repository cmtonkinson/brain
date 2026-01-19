"""Add attention decision records table.

Revision ID: 0014_attention_decision_records
Revises: 0012_attention_review_logs
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0014_attention_decision_records"
down_revision = "0012_attention_review_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create attention decision records table."""
    op.create_table(
        "attention_decision_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_reference", sa.String(length=500), nullable=False),
        sa.Column("channel", sa.String(length=100), nullable=True),
        sa.Column("base_assessment", sa.String(length=50), nullable=False),
        sa.Column("policy_outcome", sa.String(length=100), nullable=True),
        sa.Column("final_decision", sa.String(length=100), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_attention_decision_signal",
        "attention_decision_records",
        ["signal_reference"],
        unique=False,
    )


def downgrade() -> None:
    """Drop attention decision records table."""
    op.drop_index("ix_attention_decision_signal", table_name="attention_decision_records")
    op.drop_table("attention_decision_records")
