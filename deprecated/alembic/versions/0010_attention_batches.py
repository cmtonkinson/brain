"""Add attention batch scheduling tables.

Revision ID: 0010_attention_batches
Revises: 0009_attention_escalation_logs
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0010_attention_batches"
down_revision = "0009_attention_escalation_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create batch tables and link batched signals."""
    op.create_table(
        "attention_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("batch_type", sa.String(length=50), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=True),
        sa.Column("category", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "attention_batch_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["attention_batches.id"]),
    )
    op.add_column(
        "attention_batched_signals",
        sa.Column("batch_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_attention_batched_batch",
        "attention_batched_signals",
        "attention_batches",
        ["batch_id"],
        ["id"],
    )
    op.create_index(
        "ix_attention_batches_owner_time",
        "attention_batches",
        ["owner", "scheduled_for"],
        unique=False,
    )


def downgrade() -> None:
    """Drop batch tables and unlink batched signals."""
    op.drop_index("ix_attention_batches_owner_time", table_name="attention_batches")
    op.drop_constraint(
        "fk_attention_batched_batch",
        "attention_batched_signals",
        type_="foreignkey",
    )
    op.drop_column("attention_batched_signals", "batch_id")
    op.drop_table("attention_batch_logs")
    op.drop_table("attention_batches")
