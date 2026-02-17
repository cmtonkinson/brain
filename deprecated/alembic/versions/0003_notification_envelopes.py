"""Add notification envelope and provenance tables.

Revision ID: 0003_notification_envelopes
Revises: 0002_timezone_columns
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_notification_envelopes"
down_revision = "0002_timezone_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create notification envelope and provenance input tables."""
    op.create_table(
        "notification_envelopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("source_component", sa.String(length=200), nullable=False),
        sa.Column("origin_signal", sa.String(length=200), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "notification_provenance_inputs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("envelope_id", sa.Integer(), nullable=False),
        sa.Column("input_type", sa.String(length=200), nullable=False),
        sa.Column("reference", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["envelope_id"], ["notification_envelopes.id"]),
    )
    op.create_index(
        "ix_notification_provenance_envelope_id",
        "notification_provenance_inputs",
        ["envelope_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop notification envelope and provenance input tables."""
    op.drop_index(
        "ix_notification_provenance_envelope_id",
        table_name="notification_provenance_inputs",
    )
    op.drop_table("notification_provenance_inputs")
    op.drop_table("notification_envelopes")
