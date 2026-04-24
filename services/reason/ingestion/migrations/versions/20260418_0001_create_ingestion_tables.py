"""create ingestion service tables"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from lib.shared.ids import ulid_domain_type
from services.reason.ingestion.data.runtime import ingestion_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260418_0001"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical Ingestion Service-owned schema name."""
    return ingestion_postgres_schema()


def upgrade() -> None:
    """Create Ingestion Service authoritative schema objects."""
    schema = _schema()

    # -- ingestions --
    op.create_table(
        "ingestions",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(256), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("source_actor", sa.String(512), nullable=True),
        sa.Column("capture_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mime_type", sa.String(256), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index("ix_ingestions_status", "ingestions", ["status"], schema=schema)
    op.create_index(
        "ix_ingestions_created_at", "ingestions", ["created_at"], schema=schema
    )

    # -- ingestion_stage_runs --
    op.create_table(
        "ingestion_stage_runs",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("ingestion_id", sa.LargeBinary(16), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "ix_stage_runs_ingestion_id",
        "ingestion_stage_runs",
        ["ingestion_id"],
        schema=schema,
    )
    op.create_index(
        "ix_stage_runs_ingestion_stage",
        "ingestion_stage_runs",
        ["ingestion_id", "stage"],
        schema=schema,
    )

    # -- stage_artifact_outcomes --
    op.create_table(
        "stage_artifact_outcomes",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("ingestion_id", sa.LargeBinary(16), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("object_key", sa.String(256), nullable=True),
        sa.Column("parent_object_key", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "ix_outcomes_ingestion_id",
        "stage_artifact_outcomes",
        ["ingestion_id"],
        schema=schema,
    )
    op.create_index(
        "ix_outcomes_ingestion_stage",
        "stage_artifact_outcomes",
        ["ingestion_id", "stage"],
        schema=schema,
    )
    op.create_index(
        "ix_outcomes_object_key",
        "stage_artifact_outcomes",
        ["object_key"],
        schema=schema,
    )

    # -- extraction_metadata --
    op.create_table(
        "extraction_metadata",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("object_key", sa.String(256), nullable=False),
        sa.Column("method", sa.String(128), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_unique_constraint(
        "uq_extraction_metadata_object_key",
        "extraction_metadata",
        ["object_key"],
        schema=schema,
    )

    # -- normalization_metadata --
    op.create_table(
        "normalization_metadata",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("object_key", sa.String(256), nullable=False),
        sa.Column("method", sa.String(128), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_unique_constraint(
        "uq_normalization_metadata_object_key",
        "normalization_metadata",
        ["object_key"],
        schema=schema,
    )

    # -- artifact_provenance --
    op.create_table(
        "artifact_provenance",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("object_key", sa.String(256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_unique_constraint(
        "uq_artifact_provenance_object_key",
        "artifact_provenance",
        ["object_key"],
        schema=schema,
    )

    # -- provenance_sources --
    op.create_table(
        "provenance_sources",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("provenance_id", sa.LargeBinary(16), nullable=False),
        sa.Column("ingestion_id", sa.LargeBinary(16), nullable=False),
        sa.Column("source_type", sa.String(256), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("source_actor", sa.String(512), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        schema=schema,
    )
    op.create_unique_constraint(
        "uq_provenance_sources_identity",
        "provenance_sources",
        ["provenance_id", "ingestion_id", "source_type"],
        schema=schema,
    )
    op.create_index(
        "ix_provenance_sources_provenance_id",
        "provenance_sources",
        ["provenance_id"],
        schema=schema,
    )
    op.create_index(
        "ix_provenance_sources_ingestion_id",
        "provenance_sources",
        ["ingestion_id"],
        schema=schema,
    )

    # -- anchor_notes --
    op.create_table(
        "anchor_notes",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("ingestion_id", sa.LargeBinary(16), nullable=False),
        sa.Column("normalized_object_key", sa.String(256), nullable=False),
        sa.Column("vault_path", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_unique_constraint(
        "uq_anchor_notes_normalized_object_key",
        "anchor_notes",
        ["normalized_object_key"],
        schema=schema,
    )
    op.create_index(
        "ix_anchor_notes_ingestion_id",
        "anchor_notes",
        ["ingestion_id"],
        schema=schema,
    )


def downgrade() -> None:
    """Drop Ingestion Service authoritative schema objects."""
    schema = _schema()
    op.drop_table("anchor_notes", schema=schema)
    op.drop_table("provenance_sources", schema=schema)
    op.drop_table("artifact_provenance", schema=schema)
    op.drop_table("normalization_metadata", schema=schema)
    op.drop_table("extraction_metadata", schema=schema)
    op.drop_table("stage_artifact_outcomes", schema=schema)
    op.drop_table("ingestion_stage_runs", schema=schema)
    op.drop_table("ingestions", schema=schema)
