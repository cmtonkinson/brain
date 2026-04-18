"""SQLAlchemy table definitions owned by the Ingestion Service."""

from __future__ import annotations

import sqlalchemy as sa

from packages.brain_shared.ids import ulid_primary_key_column
from services.control.ingestion.data.runtime import ingestion_postgres_schema

_SCHEMA = ingestion_postgres_schema()

metadata = sa.MetaData()

# ---------------------------------------------------------------------------
# ingestions
# ---------------------------------------------------------------------------

ingestions = sa.Table(
    "ingestions",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
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
    sa.Index("ix_ingestions_status", "status"),
    sa.Index("ix_ingestions_created_at", "created_at"),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# ingestion_stage_runs
# ---------------------------------------------------------------------------

ingestion_stage_runs = sa.Table(
    "ingestion_stage_runs",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
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
    sa.Index("ix_stage_runs_ingestion_id", "ingestion_id"),
    sa.Index("ix_stage_runs_ingestion_stage", "ingestion_id", "stage"),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# stage_artifact_outcomes
# ---------------------------------------------------------------------------

stage_artifact_outcomes = sa.Table(
    "stage_artifact_outcomes",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
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
    sa.Index("ix_outcomes_ingestion_id", "ingestion_id"),
    sa.Index("ix_outcomes_ingestion_stage", "ingestion_id", "stage"),
    sa.Index("ix_outcomes_object_key", "object_key"),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# extraction_metadata
# ---------------------------------------------------------------------------

extraction_metadata = sa.Table(
    "extraction_metadata",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
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
    sa.UniqueConstraint("object_key", name="uq_extraction_metadata_object_key"),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# normalization_metadata
# ---------------------------------------------------------------------------

normalization_metadata = sa.Table(
    "normalization_metadata",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
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
    sa.UniqueConstraint("object_key", name="uq_normalization_metadata_object_key"),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# artifact_provenance
# ---------------------------------------------------------------------------

artifact_provenance = sa.Table(
    "artifact_provenance",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
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
    sa.UniqueConstraint("object_key", name="uq_artifact_provenance_object_key"),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# provenance_sources
# ---------------------------------------------------------------------------

provenance_sources = sa.Table(
    "provenance_sources",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column("provenance_id", sa.LargeBinary(16), nullable=False),
    sa.Column("ingestion_id", sa.LargeBinary(16), nullable=False),
    sa.Column("source_type", sa.String(256), nullable=False),
    sa.Column("source_uri", sa.Text(), nullable=True),
    sa.Column("source_actor", sa.String(512), nullable=True),
    sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint(
        "provenance_id",
        "ingestion_id",
        "source_type",
        name="uq_provenance_sources_identity",
    ),
    sa.Index("ix_provenance_sources_provenance_id", "provenance_id"),
    sa.Index("ix_provenance_sources_ingestion_id", "ingestion_id"),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# anchor_notes
# ---------------------------------------------------------------------------

anchor_notes = sa.Table(
    "anchor_notes",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
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
    sa.UniqueConstraint(
        "normalized_object_key", name="uq_anchor_notes_normalized_object_key"
    ),
    sa.Index("ix_anchor_notes_ingestion_id", "ingestion_id"),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# ingestion_indexing_runs
# ---------------------------------------------------------------------------

ingestion_indexing_runs = sa.Table(
    "ingestion_indexing_runs",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column("ingestion_id", sa.LargeBinary(16), nullable=False),
    sa.Column("job_id", sa.String(64), nullable=True),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("embedding_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("error", sa.Text(), nullable=True),
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
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    sa.Index("ix_indexing_runs_ingestion_id", "ingestion_id"),
    sa.Index("ix_indexing_runs_status", "status"),
    schema=_SCHEMA,
)
