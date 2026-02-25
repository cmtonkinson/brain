"""create capability engine tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from packages.brain_shared.ids.constants import ULID_DOMAIN_NAME
from services.action.capability_engine.data.runtime import (
    capability_engine_postgres_schema,
)

# revision identifiers, used by Alembic.
revision = "20260225_0001"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical CES-owned schema name."""
    return capability_engine_postgres_schema()


def _ulid_domain(schema: str) -> postgresql.DOMAIN:
    """Return schema-local ``ulid_bin`` domain reference."""
    return postgresql.DOMAIN(
        name=ULID_DOMAIN_NAME,
        data_type=postgresql.BYTEA(),
        schema=schema,
        create_type=False,
    )


def upgrade() -> None:
    """Create CES authoritative schema objects."""
    schema = _schema()

    op.create_table(
        "invocation_audits",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("envelope_id", sa.String(length=26), nullable=False),
        sa.Column("trace_id", sa.String(length=26), nullable=False),
        sa.Column("parent_id", sa.String(length=26), nullable=False, server_default=""),
        sa.Column("invocation_id", sa.String(length=26), nullable=False),
        sa.Column(
            "parent_invocation_id",
            sa.String(length=26),
            nullable=False,
            server_default="",
        ),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=128), nullable=False),
        sa.Column("capability_id", sa.String(length=128), nullable=False),
        sa.Column("capability_version", sa.String(length=32), nullable=False),
        sa.Column("policy_decision_id", sa.String(length=26), nullable=False),
        sa.Column("policy_regime_id", sa.String(length=26), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column(
            "reason_codes", sa.String(length=2048), nullable=False, server_default=""
        ),
        sa.Column(
            "proposal_token", sa.String(length=64), nullable=False, server_default=""
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )


def downgrade() -> None:
    """Drop CES authoritative schema objects."""
    op.drop_table("invocation_audits", schema=_schema())
