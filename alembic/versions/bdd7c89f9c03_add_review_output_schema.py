"""Add review output schema

Revision ID: bdd7c89f9c03
Revises: 0019_trace_id_consolidation
Create Date: 2026-01-21 12:32:31.097527

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "bdd7c89f9c03"
down_revision = "0019_trace_id_consolidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create review_outputs table
    op.create_table(
        "review_outputs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_execution_id", sa.Integer(), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("orphaned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failing_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ignored_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["job_execution_id"], ["executions.id"]),
    )

    # Create review_items table
    op.create_table(
        "review_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("review_output_id", sa.Integer(), nullable=False),
        sa.Column("schedule_id", sa.Integer(), nullable=False),
        sa.Column("task_intent_id", sa.Integer(), nullable=False),
        sa.Column("issue_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["review_output_id"], ["review_outputs.id"]),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"]),
        sa.ForeignKeyConstraint(["task_intent_id"], ["task_intents.id"]),
    )


def downgrade() -> None:
    op.drop_table("review_items")
    op.drop_table("review_outputs")
