"""Add attention batch summaries and items.

Revision ID: 0011_attention_batch_summaries
Revises: 0010_attention_batches
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011_attention_batch_summaries"
down_revision = "0010_attention_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create batch summaries and items tables."""
    op.create_table(
        "attention_batch_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["attention_batches.id"]),
    )
    op.create_table(
        "attention_batch_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("signal_reference", sa.String(length=500), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["attention_batches.id"]),
    )


def downgrade() -> None:
    """Drop batch summaries and items tables."""
    op.drop_table("attention_batch_items")
    op.drop_table("attention_batch_summaries")
