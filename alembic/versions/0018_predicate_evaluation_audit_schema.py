"""Create predicate evaluation audit tables.

Revision ID: 0018_predicate_evaluation_audit_schema
Revises: 0017_scheduler_audit_schema
Create Date: 2026-02-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0018_predicate_evaluation_audit_schema"
down_revision = "0017_scheduler_audit_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create predicate evaluation audit tables."""
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
    predicate_value_type_enum = sa.Enum(
        "string",
        "number",
        "boolean",
        "timestamp",
        name="predicate_value_type",
        native_enum=False,
    )
    predicate_eval_status_enum = sa.Enum(
        "true",
        "false",
        "error",
        name="predicate_evaluation_status_audit",
        native_enum=False,
    )

    op.create_table(
        "predicate_evaluation_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evaluation_id", sa.String(length=200), nullable=False),
        sa.Column(
            "schedule_id",
            sa.Integer(),
            sa.ForeignKey("schedules.id", name="fk_predicate_eval_schedule"),
            nullable=False,
        ),
        sa.Column(
            "execution_id",
            sa.Integer(),
            sa.ForeignKey("executions.id", name="fk_predicate_eval_execution"),
            nullable=True,
        ),
        sa.Column(
            "task_intent_id",
            sa.Integer(),
            sa.ForeignKey("task_intents.id", name="fk_predicate_eval_task_intent"),
            nullable=False,
        ),
        sa.Column("actor_type", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.String(length=200), nullable=True),
        sa.Column("actor_channel", sa.String(length=100), nullable=False),
        sa.Column("actor_privilege_level", sa.String(length=50), nullable=False),
        sa.Column("actor_autonomy_level", sa.String(length=50), nullable=False),
        sa.Column("trace_id", sa.String(length=200), nullable=False),
        sa.Column("request_id", sa.String(length=200), nullable=True),
        sa.Column("predicate_subject", sa.String(length=200), nullable=False),
        sa.Column("predicate_operator", predicate_operator_enum, nullable=False),
        sa.Column("predicate_value", sa.String(length=500), nullable=True),
        sa.Column("predicate_value_type", predicate_value_type_enum, nullable=False),
        sa.Column("evaluation_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", predicate_eval_status_enum, nullable=False),
        sa.Column("result_code", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("observed_value", sa.String(length=500), nullable=True),
        sa.Column("error_code", sa.String(length=200), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("authorization_decision", sa.String(length=50), nullable=False),
        sa.Column("authorization_reason_code", sa.String(length=200), nullable=True),
        sa.Column("authorization_reason_message", sa.Text(), nullable=True),
        sa.Column("authorization_policy_name", sa.String(length=200), nullable=True),
        sa.Column("authorization_policy_version", sa.String(length=50), nullable=True),
        sa.Column("provider_name", sa.String(length=200), nullable=False),
        sa.Column("provider_attempt", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("evaluation_id", name="uq_predicate_eval_audit_evaluation_id"),
    )

    op.create_index(
        "ix_predicate_eval_audit_schedule_id",
        "predicate_evaluation_audit_logs",
        ["schedule_id"],
    )
    op.create_index(
        "ix_predicate_eval_audit_execution_id",
        "predicate_evaluation_audit_logs",
        ["execution_id"],
    )
    op.create_index(
        "ix_predicate_eval_audit_evaluated_at",
        "predicate_evaluation_audit_logs",
        ["evaluated_at"],
    )


def downgrade() -> None:
    """Drop predicate evaluation audit tables."""
    op.drop_index(
        "ix_predicate_eval_audit_evaluated_at",
        table_name="predicate_evaluation_audit_logs",
    )
    op.drop_index(
        "ix_predicate_eval_audit_execution_id",
        table_name="predicate_evaluation_audit_logs",
    )
    op.drop_index(
        "ix_predicate_eval_audit_schedule_id",
        table_name="predicate_evaluation_audit_logs",
    )
    op.drop_table("predicate_evaluation_audit_logs")
