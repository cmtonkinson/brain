"""Create ingestion_stage_runs table for stage outcome tracking.

Revision ID: 0028_ingestion_stage_runs_table
Revises: 0027_ingestion_index_updates_and_embedding_dispatches
Create Date: 2026-02-02 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0028_ingestion_stage_runs_table"
down_revision = "0027_ingestion_index_updates_and_embedding_dispatches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create ingestion_stage_runs table with timing and outcome fields."""
    stage_enum = sa.Enum(
        "store",
        "extract",
        "normalize",
        "anchor",
        name="ingestion_stage",
        native_enum=False,
    )
    status_enum = sa.Enum(
        "success",
        "failed",
        "skipped",
        name="ingestion_artifact_status",
        native_enum=False,
    )
    op.create_table(
        "ingestion_stage_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "ingestion_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("ingestions.id"),
            nullable=False,
        ),
        sa.Column("stage", stage_enum, nullable=False),
        sa.Column("status", status_enum, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "stage IN ('store', 'extract', 'normalize', 'anchor')",
            name="ck_ingestion_stage_runs_stage",
        ),
        sa.CheckConstraint(
            "status IN ('success', 'failed', 'skipped')",
            name="ck_ingestion_stage_runs_status",
        ),
    )


def downgrade() -> None:
    """Drop ingestion_stage_runs table."""
    op.drop_table("ingestion_stage_runs")
