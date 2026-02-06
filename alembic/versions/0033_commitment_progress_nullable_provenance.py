"""Make commitment_progress.provenance_id nullable.

Revision ID: 0033_commitment_progress_nullable_provenance
Revises: 0032_commitment_progress_table
Create Date: 2026-02-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0033_commitment_progress_nullable_provenance"
down_revision = "0032_commitment_progress_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Make provenance_id nullable to support progress tracking for events without artifacts."""
    op.alter_column(
        "commitment_progress",
        "provenance_id",
        existing_type=sa.Uuid(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    """Restore provenance_id to non-nullable."""
    # Note: This will fail if there are any NULL provenance_id values
    op.alter_column(
        "commitment_progress",
        "provenance_id",
        existing_type=sa.Uuid(as_uuid=True),
        nullable=False,
    )
