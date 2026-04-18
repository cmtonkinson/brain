"""create job service tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from packages.brain_shared.ids.constants import ULID_DOMAIN_NAME
from services.control.job.data.runtime import job_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260418_0001"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical Job Service-owned schema name."""
    return job_postgres_schema()


def _ulid_domain(schema: str) -> postgresql.DOMAIN:
    """Return schema-local ``ulid_bin`` domain reference."""
    return postgresql.DOMAIN(
        name=ULID_DOMAIN_NAME,
        data_type=postgresql.BYTEA(),
        schema=schema,
        create_type=False,
    )


def upgrade() -> None:
    """Create Job Service authoritative schema objects."""
    schema = _schema()

    # -- job_intents --
    op.create_table(
        "job_intents",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("action_kind", sa.String(length=64), nullable=False),
        sa.Column("capability_id", sa.String(length=255), nullable=False),
        sa.Column("input_payload", postgresql.JSONB(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("origin_reference", sa.String(length=1024), nullable=True),
        sa.Column("created_by_actor", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("superseded_by_id", sa.LargeBinary(length=16), nullable=True),
        schema=schema,
    )

    # -- jobs --
    op.create_table(
        "jobs",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("job_intent_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("schedule_type", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", sa.String(length=32), nullable=True),
        sa.Column(
            "failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("retry_max_attempts", sa.Integer(), nullable=False),
        sa.Column("retry_backoff_strategy", sa.String(length=32), nullable=False),
        sa.Column("retry_backoff_base_seconds", sa.Integer(), nullable=False),
        sa.Column("origin_trace_id", sa.String(length=128), nullable=False),
        sa.Column("origin_envelope_id", sa.String(length=128), nullable=False),
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
    op.create_index("ix_jobs_state", "jobs", ["state"], schema=schema)
    op.create_index("ix_jobs_schedule_type", "jobs", ["schedule_type"], schema=schema)
    op.create_index("ix_jobs_next_run_at", "jobs", ["next_run_at"], schema=schema)

    # -- executions --
    op.create_table(
        "executions",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("job_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("job_intent_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("retry_backoff_strategy", sa.String(length=32), nullable=True),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column("parent_envelope_id", sa.String(length=128), nullable=False),
        sa.Column("trigger_source", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_unique_constraint(
        "uq_executions_job_trace", "executions", ["job_id", "trace_id"], schema=schema
    )
    op.create_index("ix_executions_job_id", "executions", ["job_id"], schema=schema)
    op.create_index(
        "ix_executions_status_retry",
        "executions",
        ["status", "retry_after"],
        schema=schema,
    )

    # -- job_mutation_audits --
    op.create_table(
        "job_mutation_audits",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("job_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor_type", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column("diff_summary", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "ix_job_mutation_audits_job_id",
        "job_mutation_audits",
        ["job_id"],
        schema=schema,
    )

    # -- execution_audits --
    op.create_table(
        "execution_audits",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("execution_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("job_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "ix_execution_audits_execution_id",
        "execution_audits",
        ["execution_id"],
        schema=schema,
    )

    # -- predicate_evaluations --
    op.create_table(
        "predicate_evaluations",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("job_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("predicate_subject", sa.String(length=512), nullable=False),
        sa.Column("predicate_operator", sa.String(length=32), nullable=False),
        sa.Column("predicate_value", sa.String(length=1024), nullable=True),
        sa.Column("resolved_value", sa.String(length=1024), nullable=True),
        sa.Column("authorization_decision", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "ix_predicate_evaluations_job_id",
        "predicate_evaluations",
        ["job_id"],
        schema=schema,
    )

    # -- review_outputs --
    op.create_table(
        "review_outputs",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("orphaned_count", sa.Integer(), nullable=False),
        sa.Column("failing_count", sa.Integer(), nullable=False),
        sa.Column("ignored_count", sa.Integer(), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )

    # -- review_items --
    op.create_table(
        "review_items",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("review_output_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("job_id", sa.LargeBinary(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "ix_review_items_review_output_id",
        "review_items",
        ["review_output_id"],
        schema=schema,
    )


def downgrade() -> None:
    """Drop Job Service authoritative schema objects."""
    schema = _schema()
    op.drop_table("review_items", schema=schema)
    op.drop_table("review_outputs", schema=schema)
    op.drop_table("predicate_evaluations", schema=schema)
    op.drop_table("execution_audits", schema=schema)
    op.drop_table("job_mutation_audits", schema=schema)
    op.drop_table("executions", schema=schema)
    op.drop_table("jobs", schema=schema)
    op.drop_table("job_intents", schema=schema)
