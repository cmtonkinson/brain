"""Create artifacts and ingestion_artifacts tables.

Revision ID: 0022_artifacts_tables
Revises: 0021_ingestions_table
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0022_artifacts_tables"
down_revision = "0021_ingestions_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create artifacts and ingestion_artifacts tables."""
    artifact_type_enum = sa.Enum(
        "raw",
        "extracted",
        "normalized",
        name="artifact_type",
        native_enum=False,
    )
    stage_enum = sa.Enum(
        "store",
        "extract",
        "normalize",
        "anchor",
        name="ingestion_stage",
        native_enum=False,
    )
    parent_stage_enum = sa.Enum(
        "store",
        "extract",
        "normalize",
        name="artifact_parent_stage",
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
        "artifacts",
        sa.Column("object_key", sa.Text(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=True),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column("artifact_type", artifact_type_enum, nullable=False),
        sa.Column("first_ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "parent_object_key",
            sa.Text(),
            sa.ForeignKey("artifacts.object_key"),
            nullable=True,
        ),
        sa.Column("parent_stage", parent_stage_enum, nullable=True),
        sa.CheckConstraint(
            "artifact_type IN ('raw', 'extracted', 'normalized')",
            name="ck_artifacts_artifact_type",
        ),
        sa.CheckConstraint(
            "parent_stage IS NULL OR parent_stage IN ('store', 'extract', 'normalize')",
            name="ck_artifacts_parent_stage",
        ),
    )

    op.create_table(
        "ingestion_artifacts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("ingestion_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("stage", stage_enum, nullable=False),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", status_enum, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "stage IN ('store', 'extract', 'normalize', 'anchor')",
            name="ck_ingestion_artifacts_stage",
        ),
        sa.CheckConstraint(
            "status IN ('success', 'failed', 'skipped')",
            name="ck_ingestion_artifacts_status",
        ),
        sa.ForeignKeyConstraint(["ingestion_id"], ["ingestions.id"]),
        sa.ForeignKeyConstraint(["object_key"], ["artifacts.object_key"]),
        sa.UniqueConstraint(
            "ingestion_id",
            "stage",
            "object_key",
            name="uq_ingestion_stage_object",
        ),
    )


def downgrade() -> None:
    """Drop artifacts and ingestion_artifacts tables."""
    op.drop_table("ingestion_artifacts")
    op.drop_table("artifacts")
