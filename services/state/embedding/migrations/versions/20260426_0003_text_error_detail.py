"""widen embeddings.error_detail from String(1024) to Text"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from services.state.embedding.data.runtime import embedding_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260426_0003"
down_revision = "20260220_0002"
branch_labels = None
depends_on = None


def _schema() -> str:
    return embedding_postgres_schema()


def upgrade() -> None:
    """Alter error_detail to TEXT to avoid silent truncation of long error messages."""
    op.alter_column(
        "embeddings",
        "error_detail",
        type_=sa.Text(),
        existing_type=sa.String(1024),
        schema=_schema(),
    )


def downgrade() -> None:
    """Revert error_detail to String(1024)."""
    op.alter_column(
        "embeddings",
        "error_detail",
        type_=sa.String(1024),
        existing_type=sa.Text(),
        schema=_schema(),
    )
