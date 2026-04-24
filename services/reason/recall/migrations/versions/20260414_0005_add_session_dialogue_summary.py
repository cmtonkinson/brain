"""add rolling dialogue summary to session"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from services.reason.recall.data.runtime import memory_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260414_0005"
down_revision = "20260413_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add rolling dialogue summary columns to session table."""
    schema = memory_postgres_schema()
    op.add_column(
        "session",
        sa.Column("dialogue_summary", sa.Text(), nullable=True),
        schema=schema,
    )
    op.add_column(
        "session",
        sa.Column("dialogue_summary_token_count", sa.Integer(), nullable=True),
        schema=schema,
    )
    op.create_check_constraint(
        "ck_session_dialogue_summary_token_count_nonnegative",
        "session",
        "dialogue_summary_token_count IS NULL OR dialogue_summary_token_count >= 0",
        schema=schema,
    )


def downgrade() -> None:
    """Remove rolling dialogue summary columns from session table."""
    schema = memory_postgres_schema()
    op.drop_constraint(
        "ck_session_dialogue_summary_token_count_nonnegative",
        "session",
        schema=schema,
        type_="check",
    )
    op.drop_column("session", "dialogue_summary_token_count", schema=schema)
    op.drop_column("session", "dialogue_summary", schema=schema)
