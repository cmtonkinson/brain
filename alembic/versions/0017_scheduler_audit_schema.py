"""Create scheduler audit tables for schedule changes and execution outcomes.

Revision ID: 0017_scheduler_audit_schema
Revises: 0016_scheduler_schema_migrations
Create Date: 2026-02-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0017_scheduler_audit_schema"
down_revision = "0016_scheduler_schema_migrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create scheduler audit tables for schedule mutations and executions."""
    schedule_audit_event_enum = sa.Enum(
        "create",
        "update",
        "pause",
        "resume",
        "delete",
        "run_now",
        name="schedule_audit_event_type",
        native_enum=False,
    )
    execution_status_enum = sa.Enum(
        "queued",
        "running",
        "succeeded",
        "failed",
        "retry_scheduled",
        "canceled",
        name="execution_status",
        native_enum=False,
    )

    op.create_table(
        "schedule_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "schedule_id",
            sa.Integer(),
            sa.ForeignKey("schedules.id", name="fk_schedule_audit_schedule"),
            nullable=False,
        ),
        sa.Column(
            "task_intent_id",
            sa.Integer(),
            sa.ForeignKey("task_intents.id", name="fk_schedule_audit_task_intent"),
            nullable=False,
        ),
        sa.Column("event_type", schedule_audit_event_enum, nullable=False),
        sa.Column("actor_type", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.String(length=200), nullable=True),
        sa.Column("actor_channel", sa.String(length=100), nullable=False),
        sa.Column("trace_id", sa.String(length=200), nullable=False),
        sa.Column("request_id", sa.String(length=200), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("diff_summary", sa.String(length=1000), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "execution_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "execution_id",
            sa.Integer(),
            sa.ForeignKey("executions.id", name="fk_execution_audit_execution"),
            nullable=False,
        ),
        sa.Column(
            "schedule_id",
            sa.Integer(),
            sa.ForeignKey("schedules.id", name="fk_execution_audit_schedule"),
            nullable=False,
        ),
        sa.Column(
            "task_intent_id",
            sa.Integer(),
            sa.ForeignKey("task_intents.id", name="fk_execution_audit_task_intent"),
            nullable=False,
        ),
        sa.Column("status", execution_status_enum, nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=200), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.String(length=200), nullable=True),
        sa.Column("actor_channel", sa.String(length=100), nullable=False),
        sa.Column("actor_context", sa.String(length=200), nullable=True),
        sa.Column("trace_id", sa.String(length=200), nullable=False),
        sa.Column("request_id", sa.String(length=200), nullable=True),
        sa.Column("correlation_id", sa.String(length=200), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index(
        "ix_schedule_audit_logs_schedule_id",
        "schedule_audit_logs",
        ["schedule_id"],
    )
    op.create_index(
        "ix_execution_audit_logs_execution_id",
        "execution_audit_logs",
        ["execution_id"],
    )
    op.create_index(
        "ix_execution_audit_logs_schedule_id",
        "execution_audit_logs",
        ["schedule_id"],
    )


def downgrade() -> None:
    """Drop scheduler audit tables."""
    op.drop_index(
        "ix_execution_audit_logs_schedule_id",
        table_name="execution_audit_logs",
    )
    op.drop_index(
        "ix_execution_audit_logs_execution_id",
        table_name="execution_audit_logs",
    )
    op.drop_index(
        "ix_schedule_audit_logs_schedule_id",
        table_name="schedule_audit_logs",
    )
    op.drop_table("execution_audit_logs")
    op.drop_table("schedule_audit_logs")
