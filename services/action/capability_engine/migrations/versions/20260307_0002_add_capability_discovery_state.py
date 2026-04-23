"""add capability discovery state"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from lib.shared.ids.constants import ULID_DOMAIN_NAME
from services.action.capability_engine.data.runtime import (
    capability_engine_postgres_schema,
)

# revision identifiers, used by Alembic.
revision = "20260307_0002"
down_revision = "20260225_0001"
branch_labels = None
depends_on = None


def _ulid_domain(schema: str) -> postgresql.DOMAIN:
    """Return schema-local ``ulid_bin`` domain reference."""
    return postgresql.DOMAIN(
        name=ULID_DOMAIN_NAME,
        data_type=postgresql.BYTEA(),
        schema=schema,
        create_type=False,
    )


def upgrade() -> None:
    """Create CES-owned capability discovery state table."""
    schema = capability_engine_postgres_schema()
    op.create_table(
        "capability_discovery_state",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("capability_id", sa.String(length=128), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("chunk_ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "capability_id", name="uq_capability_discovery_state_capability_id"
        ),
        schema=schema,
    )


def downgrade() -> None:
    """Drop CES-owned capability discovery state table."""
    op.drop_table(
        "capability_discovery_state",
        schema=capability_engine_postgres_schema(),
    )
