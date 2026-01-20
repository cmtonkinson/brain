"""Consolidate scheduler correlation ids into trace ids.

Revision ID: 0019_trace_id_consolidation
Revises: 0018_predicate_evaluation_audit_schema
Create Date: 2026-02-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0019_trace_id_consolidation"
down_revision = "0018_predicate_evaluation_audit_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rename correlation_id fields to trace_id and drop redundant columns."""
    op.alter_column(
        "executions",
        "correlation_id",
        new_column_name="trace_id",
    )
    op.drop_column("execution_audit_logs", "correlation_id")
    op.drop_column("predicate_evaluation_audit_logs", "correlation_id")


def downgrade() -> None:
    """Restore correlation_id columns and rename trace_id back for executions."""
    op.alter_column(
        "executions",
        "trace_id",
        new_column_name="correlation_id",
    )
    op.add_column(
        "execution_audit_logs",
        sa.Column("correlation_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "predicate_evaluation_audit_logs",
        sa.Column("correlation_id", sa.String(length=200), nullable=True),
    )
    op.execute(
        "UPDATE execution_audit_logs SET correlation_id = trace_id " "WHERE correlation_id IS NULL"
    )
    op.execute(
        "UPDATE predicate_evaluation_audit_logs SET correlation_id = trace_id "
        "WHERE correlation_id IS NULL"
    )
    op.alter_column(
        "predicate_evaluation_audit_logs",
        "correlation_id",
        nullable=False,
    )
