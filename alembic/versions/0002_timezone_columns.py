"""Use timezone-aware columns for UTC storage.

Revision ID: 0002_timezone_columns
Revises: 0001_initial
Create Date: 2025-01-02 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_timezone_columns"
down_revision = "0002_indexer_state"
branch_labels = None
depends_on = None


def _upgrade_column(table: str, column: str) -> None:
    """Alter a column to timezone-aware and preserve UTC semantics."""
    op.alter_column(
        table,
        column,
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        postgresql_using=f"\"{column}\" AT TIME ZONE 'UTC'",
    )


def _downgrade_column(table: str, column: str) -> None:
    """Alter a column to naive timestamps while keeping UTC values."""
    op.alter_column(
        table,
        column,
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        postgresql_using=f"\"{column}\" AT TIME ZONE 'UTC'",
    )


def upgrade() -> None:
    """Promote timestamp columns to timezone-aware UTC storage."""
    _upgrade_column("action_logs", "timestamp")

    _upgrade_column("conversations", "started_at")
    _upgrade_column("conversations", "last_message_at")

    _upgrade_column("tasks", "scheduled_for")
    _upgrade_column("tasks", "created_at")
    _upgrade_column("tasks", "completed_at")

    _upgrade_column("indexed_notes", "modified_at")
    _upgrade_column("indexed_notes", "last_indexed_at")

    _upgrade_column("indexed_chunks", "created_at")


def downgrade() -> None:
    """Revert timestamp columns to naive UTC storage."""
    _downgrade_column("indexed_chunks", "created_at")

    _downgrade_column("indexed_notes", "modified_at")
    _downgrade_column("indexed_notes", "last_indexed_at")

    _downgrade_column("tasks", "scheduled_for")
    _downgrade_column("tasks", "created_at")
    _downgrade_column("tasks", "completed_at")

    _downgrade_column("conversations", "started_at")
    _downgrade_column("conversations", "last_message_at")

    _downgrade_column("action_logs", "timestamp")
