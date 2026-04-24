"""SQLAlchemy table definitions for Job Service schema."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB

from lib.shared.ids import ulid_primary_key_column
from services.reason.job.data.runtime import job_postgres_schema

_SCHEMA = job_postgres_schema()

metadata = sa.MetaData()

# ---------------------------------------------------------------------------
# job_intents
# ---------------------------------------------------------------------------

job_intents = sa.Table(
    "job_intents",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column("summary", sa.String(512), nullable=False),
    sa.Column("action_kind", sa.String(64), nullable=False),
    sa.Column("op_id", sa.String(255), nullable=False),
    sa.Column("input_payload", JSONB(), nullable=False),
    sa.Column("details", sa.Text(), nullable=True),
    sa.Column("origin_reference", sa.String(1024), nullable=True),
    sa.Column("created_by_actor", sa.String(128), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column(
        "superseded_by_id",
        sa.LargeBinary(16),
        ForeignKey(f"{_SCHEMA}.job_intents.id", ondelete="SET NULL"),
        nullable=True,
    ),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------

jobs = sa.Table(
    "jobs",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column(
        "job_intent_id",
        sa.LargeBinary(16),
        ForeignKey(f"{_SCHEMA}.job_intents.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("schedule_type", sa.String(32), nullable=False),
    sa.Column("state", sa.String(32), nullable=False),
    sa.Column("timezone", sa.String(64), nullable=False),
    sa.Column("definition", JSONB(), nullable=False),
    sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_run_status", sa.String(32), nullable=True),
    sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("last_error_message", sa.Text(), nullable=True),
    sa.Column("retry_max_attempts", sa.Integer(), nullable=False),
    sa.Column("retry_backoff_strategy", sa.String(32), nullable=False),
    sa.Column("retry_backoff_base_seconds", sa.Integer(), nullable=False),
    sa.Column("origin_trace_id", sa.String(128), nullable=False),
    sa.Column("origin_envelope_id", sa.String(128), nullable=False),
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
    sa.Index("ix_jobs_state", "state"),
    sa.Index("ix_jobs_schedule_type", "schedule_type"),
    sa.Index("ix_jobs_next_run_at", "next_run_at"),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# executions
# ---------------------------------------------------------------------------

executions = sa.Table(
    "executions",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column(
        "job_id",
        sa.LargeBinary(16),
        ForeignKey(f"{_SCHEMA}.jobs.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "job_intent_id",
        sa.LargeBinary(16),
        ForeignKey(f"{_SCHEMA}.job_intents.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("attempt_number", sa.Integer(), nullable=False),
    sa.Column("max_attempts", sa.Integer(), nullable=False),
    sa.Column("retry_backoff_strategy", sa.String(32), nullable=True),
    sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
    sa.Column("trace_id", sa.String(128), nullable=False),
    sa.Column("parent_envelope_id", sa.String(128), nullable=False),
    sa.Column("trigger_source", sa.String(64), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("error_message", sa.Text(), nullable=True),
    sa.Column("error_code", sa.String(128), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.UniqueConstraint("job_id", "trace_id", name="uq_executions_job_trace"),
    sa.Index("ix_executions_job_id", "job_id"),
    sa.Index("ix_executions_status_retry", "status", "retry_after"),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# job_mutation_audits
# ---------------------------------------------------------------------------

job_mutation_audits = sa.Table(
    "job_mutation_audits",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column(
        "job_id",
        sa.LargeBinary(16),
        ForeignKey(f"{_SCHEMA}.jobs.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("event_type", sa.String(32), nullable=False),
    sa.Column("actor_type", sa.String(64), nullable=False),
    sa.Column("actor_id", sa.String(128), nullable=True),
    sa.Column("channel", sa.String(64), nullable=False),
    sa.Column("trace_id", sa.String(128), nullable=False),
    sa.Column("diff_summary", sa.Text(), nullable=True),
    sa.Column("notes", sa.Text(), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Index("ix_job_mutation_audits_job_id", "job_id"),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# execution_audits
# ---------------------------------------------------------------------------

execution_audits = sa.Table(
    "execution_audits",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column(
        "execution_id",
        sa.LargeBinary(16),
        ForeignKey(f"{_SCHEMA}.executions.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "job_id",
        sa.LargeBinary(16),
        ForeignKey(f"{_SCHEMA}.jobs.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("attempt_number", sa.Integer(), nullable=False),
    sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
    sa.Column("error_message", sa.Text(), nullable=True),
    sa.Column("error_code", sa.String(128), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Index("ix_execution_audits_execution_id", "execution_id"),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# predicate_evaluations
# ---------------------------------------------------------------------------

predicate_evaluations = sa.Table(
    "predicate_evaluations",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column(
        "job_id",
        sa.LargeBinary(16),
        ForeignKey(f"{_SCHEMA}.jobs.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("predicate_subject", sa.String(512), nullable=False),
    sa.Column("predicate_operator", sa.String(32), nullable=False),
    sa.Column("predicate_value", sa.String(1024), nullable=True),
    sa.Column("resolved_value", sa.String(1024), nullable=True),
    sa.Column("authorization_decision", sa.String(32), nullable=False),
    sa.Column("error_code", sa.String(128), nullable=True),
    sa.Column("error_message", sa.Text(), nullable=True),
    sa.Column("trace_id", sa.String(128), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Index("ix_predicate_evaluations_job_id", "job_id"),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# review_outputs
# ---------------------------------------------------------------------------

review_outputs = sa.Table(
    "review_outputs",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column("orphaned_count", sa.Integer(), nullable=False),
    sa.Column("failing_count", sa.Integer(), nullable=False),
    sa.Column("ignored_count", sa.Integer(), nullable=False),
    sa.Column("stalled_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    schema=_SCHEMA,
)

# ---------------------------------------------------------------------------
# review_items
# ---------------------------------------------------------------------------

review_items = sa.Table(
    "review_items",
    metadata,
    ulid_primary_key_column("id", schema_name=_SCHEMA),
    sa.Column(
        "review_output_id",
        sa.LargeBinary(16),
        ForeignKey(f"{_SCHEMA}.review_outputs.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "job_id",
        sa.LargeBinary(16),
        ForeignKey(f"{_SCHEMA}.jobs.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("category", sa.String(32), nullable=False),
    sa.Column("severity", sa.String(32), nullable=False),
    sa.Column("message", sa.Text(), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Index("ix_review_items_review_output_id", "review_output_id"),
    schema=_SCHEMA,
)
