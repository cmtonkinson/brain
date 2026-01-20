"""Create scheduler intent, schedule, and execution tables.

Revision ID: 0016_scheduler_schema_migrations
Revises: 0015_attention_escalation_signal_type
Create Date: 2026-02-02 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0016_scheduler_schema_migrations"
down_revision = "0015_attention_escalation_signal_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create scheduler task intent, schedule, and execution tables."""
    schedule_type_enum = sa.Enum(
        "one_time",
        "interval",
        "calendar_rule",
        "conditional",
        name="schedule_type",
        native_enum=False,
    )
    schedule_state_enum = sa.Enum(
        "draft",
        "active",
        "paused",
        "canceled",
        "archived",
        "completed",
        name="schedule_state",
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
    interval_unit_enum = sa.Enum(
        "minute",
        "hour",
        "day",
        "week",
        "month",
        name="interval_unit",
        native_enum=False,
    )
    predicate_operator_enum = sa.Enum(
        "eq",
        "neq",
        "gt",
        "gte",
        "lt",
        "lte",
        "exists",
        "matches",
        name="predicate_operator",
        native_enum=False,
    )
    evaluation_interval_unit_enum = sa.Enum(
        "minute",
        "hour",
        "day",
        "week",
        name="evaluation_interval_unit",
        native_enum=False,
    )
    predicate_eval_status_enum = sa.Enum(
        "true",
        "false",
        "error",
        "unknown",
        name="predicate_evaluation_status",
        native_enum=False,
    )
    backoff_strategy_enum = sa.Enum(
        "fixed",
        "exponential",
        "none",
        name="backoff_strategy",
        native_enum=False,
    )

    op.create_table(
        "task_intents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("creator_actor_type", sa.String(length=100), nullable=False),
        sa.Column("creator_actor_id", sa.String(length=200), nullable=True),
        sa.Column("creator_channel", sa.String(length=100), nullable=False),
        sa.Column("origin_reference", sa.String(length=500), nullable=True),
        sa.Column("superseded_by_intent_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["superseded_by_intent_id"],
            ["task_intents.id"],
            name="fk_task_intents_superseded_by",
        ),
    )

    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_intent_id",
            sa.Integer(),
            sa.ForeignKey("task_intents.id", name="fk_schedules_task_intent"),
            nullable=False,
        ),
        sa.Column("schedule_type", schedule_type_enum, nullable=False),
        sa.Column("state", schedule_state_enum, nullable=False),
        sa.Column("timezone", sa.String(length=100), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", execution_status_enum, nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_execution_id", sa.Integer(), nullable=True),
        sa.Column("created_by_actor_type", sa.String(length=100), nullable=False),
        sa.Column("created_by_actor_id", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interval_count", sa.Integer(), nullable=True),
        sa.Column("interval_unit", interval_unit_enum, nullable=True),
        sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rrule", sa.String(length=1000), nullable=True),
        sa.Column("calendar_anchor_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("predicate_subject", sa.String(length=200), nullable=True),
        sa.Column("predicate_operator", predicate_operator_enum, nullable=True),
        sa.Column("predicate_value", sa.String(length=500), nullable=True),
        sa.Column("evaluation_interval_count", sa.Integer(), nullable=True),
        sa.Column("evaluation_interval_unit", evaluation_interval_unit_enum, nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_evaluation_status", predicate_eval_status_enum, nullable=True),
        sa.Column("last_evaluation_error_code", sa.String(length=200), nullable=True),
        sa.CheckConstraint(
            "schedule_type != 'conditional' OR "
            "(evaluation_interval_count IS NOT NULL AND evaluation_interval_unit IS NOT NULL)",
            name="ck_schedules_conditional_eval_cadence",
        ),
    )

    op.create_table(
        "executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_intent_id",
            sa.Integer(),
            sa.ForeignKey("task_intents.id", name="fk_executions_task_intent"),
            nullable=False,
        ),
        sa.Column(
            "schedule_id",
            sa.Integer(),
            sa.ForeignKey("schedules.id", name="fk_executions_schedule"),
            nullable=False,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.String(length=100), nullable=False),
        sa.Column("actor_context", sa.String(length=200), nullable=True),
        sa.Column("correlation_id", sa.String(length=200), nullable=True),
        sa.Column("status", execution_status_enum, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_backoff_strategy", backoff_strategy_enum, nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=200), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
    )

    op.create_foreign_key(
        "fk_schedules_last_execution",
        "schedules",
        "executions",
        ["last_execution_id"],
        ["id"],
    )

    op.create_index("ix_schedules_next_run_at", "schedules", ["next_run_at"])
    op.create_index("ix_executions_schedule_id", "executions", ["schedule_id"])
    op.create_index("ix_executions_status", "executions", ["status"])


def downgrade() -> None:
    """Drop scheduler task intent, schedule, and execution tables."""
    op.drop_index("ix_executions_status", table_name="executions")
    op.drop_index("ix_executions_schedule_id", table_name="executions")
    op.drop_index("ix_schedules_next_run_at", table_name="schedules")

    op.drop_constraint("fk_schedules_last_execution", "schedules", type_="foreignkey")
    op.drop_table("executions")
    op.drop_table("schedules")
    op.drop_table("task_intents")
