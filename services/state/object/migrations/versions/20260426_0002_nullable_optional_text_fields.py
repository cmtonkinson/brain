"""make content_type, original_filename, source_uri nullable"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from services.state.object.data.runtime import object_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260426_0002"
down_revision = "20260223_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop NOT NULL constraint and server default from optional text columns."""
    schema = object_postgres_schema()
    for column in ("content_type", "original_filename", "source_uri"):
        op.alter_column(
            "objects",
            column,
            existing_type=sa.String(),
            nullable=True,
            server_default=None,
            schema=schema,
        )


def downgrade() -> None:
    """Restore NOT NULL constraint and empty-string server default."""
    schema = object_postgres_schema()
    lengths = {"content_type": 256, "original_filename": 512, "source_uri": 1024}
    for column, length in lengths.items():
        op.execute(f"UPDATE {schema}.objects SET {column} = '' WHERE {column} IS NULL")
        op.alter_column(
            "objects",
            column,
            existing_type=sa.String(length),
            nullable=False,
            server_default="",
            schema=schema,
        )
