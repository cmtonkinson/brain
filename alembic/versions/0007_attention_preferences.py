"""Add attention preference tables.

Revision ID: 0007_attention_preferences
Revises: 0006_attention_holding_areas
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_attention_preferences"
down_revision = "0006_attention_holding_areas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create attention preference tables."""
    op.create_table(
        "attention_quiet_hours",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("timezone", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "attention_do_not_disturb",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("timezone", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "attention_channel_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("preference", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "attention_escalation_thresholds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("signal_type", sa.String(length=200), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "attention_always_notify",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("signal_type", sa.String(length=200), nullable=False),
        sa.Column("source_component", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Drop attention preference tables."""
    op.drop_table("attention_always_notify")
    op.drop_table("attention_escalation_thresholds")
    op.drop_table("attention_channel_preferences")
    op.drop_table("attention_do_not_disturb")
    op.drop_table("attention_quiet_hours")
