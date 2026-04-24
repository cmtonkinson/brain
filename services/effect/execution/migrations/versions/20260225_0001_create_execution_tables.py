"""create execution invocation audit table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from lib.shared.ids import ulid_domain_type
from services.effect.execution.data.runtime import (
    execution_postgres_schema,
)

# revision identifiers, used by Alembic.
revision = "20260225_0001"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical Execution-owned schema name."""
    return execution_postgres_schema()


def upgrade() -> None:
    """Create Execution authoritative schema objects."""
    schema = _schema()

    op.create_table(
        "invocation_audits",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
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
        sa.Column("op_id", sa.String(length=128), nullable=False),
        sa.Column("op_version", sa.String(length=32), nullable=False),
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
    """Drop Execution authoritative schema objects."""
    op.drop_table("invocation_audits", schema=_schema())
