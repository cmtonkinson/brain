"""Create commitment review runs table.

Revision ID: 0033_commitment_review_runs_table
Revises: 0032_commitment_progress_table
Create Date: 2026-02-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0033_commitment_review_runs_table"
down_revision = "0032_commitment_progress_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create commitment_review_runs table."""
    op.create_table(
        "commitment_review_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drop commitment_review_runs table."""
    op.drop_table("commitment_review_runs")
