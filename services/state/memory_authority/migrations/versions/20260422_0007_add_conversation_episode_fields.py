"""add conversation episode fields"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from services.state.memory_authority.data.runtime import memory_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260422_0007"
down_revision = "20260414_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add MAS-owned conversation episode fields."""
    schema = memory_postgres_schema()
    op.add_column(
        "session",
        sa.Column(
            "current_conversation_episode_id", sa.String(length=26), nullable=True
        ),
        schema=schema,
    )
    op.add_column(
        "session",
        sa.Column("last_episode_inbound_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.add_column(
        "turn",
        sa.Column(
            "conversation_episode_id",
            sa.String(length=26),
            nullable=False,
            server_default="",
        ),
        schema=schema,
    )


def downgrade() -> None:
    """Remove MAS-owned conversation episode fields."""
    schema = memory_postgres_schema()
    op.drop_column("turn", "conversation_episode_id", schema=schema)
    op.drop_column("session", "last_episode_inbound_at", schema=schema)
    op.drop_column("session", "current_conversation_episode_id", schema=schema)
