"""add op discovery state table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from lib.shared.ids import ulid_domain_type
from services.effect.execution.data.runtime import (
    execution_postgres_schema,
)

# revision identifiers, used by Alembic.
revision = "20260307_0002"
down_revision = "20260225_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create Execution-owned op discovery state table."""
    schema = execution_postgres_schema()
    op.create_table(
        "op_discovery_state",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("op_id", sa.String(length=128), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("chunk_ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("op_id", name="uq_op_discovery_state_op_id"),
        schema=schema,
    )


def downgrade() -> None:
    """Drop Execution-owned op discovery state table."""
    op.drop_table(
        "op_discovery_state",
        schema=execution_postgres_schema(),
    )
