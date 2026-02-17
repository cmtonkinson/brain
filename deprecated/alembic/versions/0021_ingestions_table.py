"""Create ingestions table for intake metadata.

Revision ID: 0021_ingestions_table
Revises: 0020_review_output_surface_metadata
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0021_ingestions_table"
down_revision = "0020_review_output_surface_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create ingestions table with status constraint."""
    ingestion_status_enum = sa.Enum(
        "queued",
        "running",
        "complete",
        "failed",
        name="ingestion_status",
        native_enum=False,
    )

    op.create_table(
        "ingestions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("source_type", sa.String(length=200), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("source_actor", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", ingestion_status_enum, nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'failed')",
            name="ck_ingestions_status",
        ),
    )


def downgrade() -> None:
    """Drop ingestions table."""
    op.drop_table("ingestions")
