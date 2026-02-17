"""Create commitment progress table.

Revision ID: 0032_commitment_progress_table
Revises: 0031_commitment_schedules_table
Create Date: 2026-02-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0032_commitment_progress_table"
down_revision = "0031_commitment_schedules_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create commitment_progress table with foreign keys."""
    op.create_table(
        "commitment_progress",
        sa.Column("progress_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "commitment_id",
            sa.BigInteger(),
            sa.ForeignKey("commitments.commitment_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provenance_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("provenance_records.id"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    """Drop commitment_progress table."""
    op.drop_table("commitment_progress")
