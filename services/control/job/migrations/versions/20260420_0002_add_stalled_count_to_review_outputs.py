"""add stalled_count to review_outputs"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from services.control.job.data.runtime import job_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260420_0002"
down_revision = "20260418_0001"
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical Job Service-owned schema name."""
    return job_postgres_schema()


def upgrade() -> None:
    op.add_column(
        "review_outputs",
        sa.Column(
            "stalled_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        schema=_schema(),
    )


def downgrade() -> None:
    op.drop_column("review_outputs", "stalled_count", schema=_schema())
