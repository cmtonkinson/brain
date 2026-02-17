"""Create extraction metadata table.

Revision ID: 0024_extraction_metadata_table
Revises: 0023_provenance_tables
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0024_extraction_metadata_table"
down_revision = "0023_provenance_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the extraction_metadata table."""
    op.create_table(
        "extraction_metadata",
        sa.Column("object_key", sa.Text(), sa.ForeignKey("artifacts.object_key"), primary_key=True),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("tool_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drop the extraction_metadata table."""
    op.drop_table("extraction_metadata")
