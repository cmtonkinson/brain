"""Create provenance_records and provenance_sources tables.

Revision ID: 0023_provenance_tables
Revises: 0022_artifacts_tables
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0023_provenance_tables"
down_revision = "0022_artifacts_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create provenance record tables with dedupe constraints."""
    op.create_table(
        "provenance_records",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["object_key"], ["artifacts.object_key"]),
        sa.UniqueConstraint("object_key", name="uq_provenance_records_object_key"),
    )

    op.create_table(
        "provenance_sources",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("provenance_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("ingestion_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("source_actor", sa.Text(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["provenance_id"], ["provenance_records.id"]),
        sa.ForeignKeyConstraint(["ingestion_id"], ["ingestions.id"]),
        sa.UniqueConstraint(
            "provenance_id",
            "source_type",
            "source_uri",
            "source_actor",
            name="uq_provenance_source_dedupe",
        ),
    )


def downgrade() -> None:
    """Drop provenance record tables."""
    op.drop_table("provenance_sources")
    op.drop_table("provenance_records")
