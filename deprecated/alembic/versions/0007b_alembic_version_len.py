"""Extend alembic version column length for long revision identifiers.

Revision ID: 0007b_alembic_version_len
Revises: 0007_attention_preferences
Create Date: 2026-02-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007b_alembic_version_len"
down_revision = "0007_attention_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Expand the alembic version column for long revision IDs."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.alter_column(
        "alembic_version",
        "version_num",
        type_=sa.String(length=64),
        existing_type=sa.String(length=32),
    )


def downgrade() -> None:
    """Revert the alembic version column size."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.alter_column(
        "alembic_version",
        "version_num",
        type_=sa.String(length=32),
        existing_type=sa.String(length=64),
    )
