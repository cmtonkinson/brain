"""Create anchor note table.

Revision ID: 0026_anchor_notes_table
Revises: 0025_normalization_metadata_table
Create Date: 2026-02-02 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0026_anchor_notes_table"
down_revision = "0025_normalization_metadata_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the anchor_notes table."""
    op.create_table(
        "anchor_notes",
        sa.Column(
            "normalized_object_key",
            sa.Text(),
            sa.ForeignKey("artifacts.object_key"),
            primary_key=True,
        ),
        sa.Column(
            "ingestion_id", sa.Uuid(as_uuid=True), sa.ForeignKey("ingestions.id"), nullable=False
        ),
        sa.Column("note_uri", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drop the anchor_notes table."""
    op.drop_table("anchor_notes")
