"""add dedupe fields to creation proposals"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from services.reason.commitment.data.runtime import commitment_postgres_schema

revision = "20260419_0002"
down_revision = "20260418_0001"
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical Commitment Service-owned schema name."""
    return commitment_postgres_schema()


def upgrade() -> None:
    """Add dedupe columns to creation_proposals."""
    schema = _schema()
    op.add_column(
        "creation_proposals",
        sa.Column("matched_commitment_id", sa.String(length=26), nullable=True),
        schema=schema,
    )
    op.add_column(
        "creation_proposals",
        sa.Column("match_summary", sa.Text(), nullable=True),
        schema=schema,
    )
    op.add_column(
        "creation_proposals",
        sa.Column("dedupe_confidence", sa.Float(), nullable=True),
        schema=schema,
    )


def downgrade() -> None:
    """Remove dedupe columns from creation_proposals."""
    schema = _schema()
    op.drop_column("creation_proposals", "dedupe_confidence", schema=schema)
    op.drop_column("creation_proposals", "match_summary", schema=schema)
    op.drop_column("creation_proposals", "matched_commitment_id", schema=schema)
