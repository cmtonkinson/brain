"""SQLAlchemy table definitions for Commitment Service schema."""

from __future__ import annotations

import sqlalchemy as sa

from lib.shared.ids import ulid_primary_key_column
from services.control.commitment.data.runtime import commitment_postgres_schema

_SCHEMA = commitment_postgres_schema()

metadata = sa.MetaData()

commitments = sa.Table(
    "commitments",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column("description", sa.String(512), nullable=False),
    sa.Column("state", sa.String(32), nullable=False),
    sa.Column("provenance_reference", sa.String(255), nullable=True),
    sa.Column("ingestion_id", sa.String(255), nullable=True),
    sa.Column("source", sa.String(128), nullable=True),
    sa.Column("due_by", sa.DateTime(timezone=True), nullable=True),
    sa.Column("due_timezone", sa.String(64), nullable=True),
    sa.Column("importance", sa.Integer(), nullable=False),
    sa.Column("effort_provided", sa.Integer(), nullable=False),
    sa.Column("effort_inferred", sa.Integer(), nullable=True),
    sa.Column("urgency", sa.Integer(), nullable=False),
    sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_modified_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("ever_missed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("presented_for_review_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
    sa.Index("ix_commitments_state", "state"),
    sa.Index("ix_commitments_due_by", "due_by"),
    schema=_SCHEMA,
)

commitment_progress = sa.Table(
    "commitment_progress",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column("commitment_id", sa.LargeBinary(16), nullable=False),
    sa.Column("provenance_reference", sa.String(255), nullable=True),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("summary", sa.String(512), nullable=False),
    sa.Column("snippet", sa.Text(), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Index("ix_commitment_progress_commitment_id", "commitment_id"),
    schema=_SCHEMA,
)

commitment_transitions = sa.Table(
    "commitment_transitions",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column("commitment_id", sa.LargeBinary(16), nullable=False),
    sa.Column("from_state", sa.String(32), nullable=False),
    sa.Column("to_state", sa.String(32), nullable=False),
    sa.Column("actor", sa.String(32), nullable=False),
    sa.Column("reason", sa.Text(), nullable=True),
    sa.Column("confidence", sa.Float(), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Index("ix_commitment_transitions_commitment_id", "commitment_id"),
    sa.Index("ix_commitment_transitions_to_state", "to_state"),
    schema=_SCHEMA,
)

creation_proposals = sa.Table(
    "creation_proposals",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column("description", sa.String(512), nullable=False),
    sa.Column("provenance_reference", sa.String(255), nullable=True),
    sa.Column("ingestion_id", sa.String(255), nullable=True),
    sa.Column("source", sa.String(128), nullable=True),
    sa.Column("due_by", sa.DateTime(timezone=True), nullable=True),
    sa.Column("due_timezone", sa.String(64), nullable=True),
    sa.Column("importance", sa.Integer(), nullable=False),
    sa.Column("effort_provided", sa.Integer(), nullable=False),
    sa.Column("effort_inferred", sa.Integer(), nullable=True),
    sa.Column("requested_by", sa.String(32), nullable=False),
    sa.Column("confidence", sa.Float(), nullable=True),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("decided_by", sa.String(255), nullable=True),
    sa.Column("decision_reason", sa.Text(), nullable=True),
    sa.Column("created_commitment_id", sa.String(26), nullable=True),
    sa.Column("matched_commitment_id", sa.String(26), nullable=True),
    sa.Column("match_summary", sa.Text(), nullable=True),
    sa.Column("dedupe_confidence", sa.Float(), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    sa.Index("ix_creation_proposals_status", "status"),
    schema=_SCHEMA,
)

transition_proposals = sa.Table(
    "transition_proposals",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column("commitment_id", sa.LargeBinary(16), nullable=False),
    sa.Column("from_state", sa.String(32), nullable=False),
    sa.Column("to_state", sa.String(32), nullable=False),
    sa.Column("requested_by", sa.String(32), nullable=False),
    sa.Column("confidence", sa.Float(), nullable=True),
    sa.Column("threshold", sa.Float(), nullable=False),
    sa.Column("reason", sa.Text(), nullable=True),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("decided_by", sa.String(255), nullable=True),
    sa.Column("decision_reason", sa.Text(), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    sa.Index("ix_transition_proposals_commitment_id", "commitment_id"),
    sa.Index("ix_transition_proposals_status", "status"),
    schema=_SCHEMA,
)

review_runs = sa.Table(
    "review_runs",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column("since_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("notification_reference", sa.String(255), nullable=True),
    sa.Column("completed_count", sa.Integer(), nullable=False),
    sa.Column("missed_count", sa.Integer(), nullable=False),
    sa.Column("modified_count", sa.Integer(), nullable=False),
    sa.Column("no_due_date_count", sa.Integer(), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    schema=_SCHEMA,
)

review_items = sa.Table(
    "review_items",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column("review_run_id", sa.LargeBinary(16), nullable=False),
    sa.Column("commitment_id", sa.LargeBinary(16), nullable=False),
    sa.Column("category", sa.String(32), nullable=False),
    sa.Column("message", sa.Text(), nullable=False),
    sa.Column("presented_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Index("ix_review_items_review_run_id", "review_run_id"),
    schema=_SCHEMA,
)

commitment_job_links = sa.Table(
    "commitment_job_links",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column("commitment_id", sa.LargeBinary(16), nullable=False, unique=True),
    sa.Column("job_id", sa.String(26), nullable=True),
    sa.Column("job_timezone", sa.String(64), nullable=True),
    sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("unlinked_at", sa.DateTime(timezone=True), nullable=True),
    schema=_SCHEMA,
)
