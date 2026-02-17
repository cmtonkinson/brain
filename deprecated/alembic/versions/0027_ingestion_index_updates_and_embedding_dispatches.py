"""Create ingestion index handoff and embeddings dispatch tables.

Revision ID: 0027_ingestion_index_updates_and_embedding_dispatches
Revises: 0026_anchor_notes_table
Create Date: 2026-02-02 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0027_ingestion_index_updates_and_embedding_dispatches"
down_revision = "0026_anchor_notes_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create ingestion index handoff and embeddings dispatch tables."""
    status_enum = sa.Enum(
        "success",
        "failed",
        "skipped",
        name="ingestion_artifact_status",
        native_enum=False,
    )
    op.create_table(
        "ingestion_index_updates",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "ingestion_id", sa.Uuid(as_uuid=True), sa.ForeignKey("ingestions.id"), nullable=False
        ),
        sa.Column("status", status_enum, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ingestion_embedding_dispatches",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "ingestion_id", sa.Uuid(as_uuid=True), sa.ForeignKey("ingestions.id"), nullable=False
        ),
        sa.Column(
            "normalized_object_key",
            sa.Text(),
            sa.ForeignKey("artifacts.object_key"),
            nullable=False,
        ),
        sa.Column("status", status_enum, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drop ingestion index handoff and embeddings dispatch tables."""
    op.drop_table("ingestion_embedding_dispatches")
    op.drop_table("ingestion_index_updates")
