"""Add deferred and batched signal holding tables.

Revision ID: 0006_attention_holding_areas
Revises: 0005_attention_audit_logs
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_attention_holding_areas"
down_revision = "0005_attention_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create deferred and batched signal holding tables."""
    op.create_table(
        "attention_deferred_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("signal_reference", sa.String(length=500), nullable=False),
        sa.Column("source_component", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reevaluate_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_attention_deferred_owner_time",
        "attention_deferred_signals",
        ["owner", "reevaluate_at"],
        unique=False,
    )
    op.create_table(
        "attention_batched_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("signal_reference", sa.String(length=500), nullable=False),
        sa.Column("source_component", sa.String(length=200), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_attention_batched_owner_topic",
        "attention_batched_signals",
        ["owner", "topic", "category"],
        unique=False,
    )


def downgrade() -> None:
    """Drop deferred and batched signal holding tables."""
    op.drop_index("ix_attention_batched_owner_topic", table_name="attention_batched_signals")
    op.drop_table("attention_batched_signals")
    op.drop_index("ix_attention_deferred_owner_time", table_name="attention_deferred_signals")
    op.drop_table("attention_deferred_signals")
