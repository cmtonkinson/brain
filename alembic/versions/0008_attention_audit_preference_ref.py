"""Add preference reference to attention audit logs.

Revision ID: 0008_attention_audit_preference_ref
Revises: 0007_attention_preferences
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008_attention_audit_preference_ref"
down_revision = "0007b_alembic_version_len"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add preference reference column to attention audit logs."""
    op.add_column(
        "attention_audit_logs",
        sa.Column("preference_reference", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    """Remove preference reference column from attention audit logs."""
    op.drop_column("attention_audit_logs", "preference_reference")
