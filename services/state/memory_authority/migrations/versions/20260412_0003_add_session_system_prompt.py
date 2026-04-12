"""add system_prompt to session"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from services.state.memory_authority.data.runtime import memory_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260412_0003"
down_revision = "20260412_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add system_prompt column to session table."""
    schema = memory_postgres_schema()
    op.add_column(
        "session",
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        schema=schema,
    )
    op.alter_column("session", "system_prompt", server_default=None, schema=schema)


def downgrade() -> None:
    """Remove system_prompt column from session table."""
    schema = memory_postgres_schema()
    op.drop_column("session", "system_prompt", schema=schema)
