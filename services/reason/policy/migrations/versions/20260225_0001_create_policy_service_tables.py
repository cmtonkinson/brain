"""create policy service tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from lib.shared.ids import ulid_domain_type
from services.reason.policy.data.runtime import policy_service_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260225_0001"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical Policy-owned schema name."""
    return policy_service_postgres_schema()


def upgrade() -> None:
    """Create Policy authoritative schema objects."""
    schema = _schema()

    op.create_table(
        "policy_regimes",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_json", sa.String(), nullable=False),
        sa.Column("policy_id", sa.String(length=128), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("policy_hash", name="uq_policy_regimes_policy_hash"),
        schema=schema,
    )

    op.create_table(
        "active_policy_regime",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("pointer_id", sa.String(length=16), nullable=False),
        sa.Column("policy_regime_id", ulid_domain_type(schema), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("pointer_id", name="uq_active_policy_regime_pointer_id"),
        sa.ForeignKeyConstraint(
            ["policy_regime_id"],
            [f"{schema}.policy_regimes.id"],
            ondelete="RESTRICT",
        ),
        schema=schema,
    )

    op.create_table(
        "policy_decisions",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("policy_regime_id", ulid_domain_type(schema), nullable=False),
        sa.Column("envelope_id", sa.String(length=26), nullable=False),
        sa.Column("trace_id", sa.String(length=26), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=128), nullable=False),
        sa.Column("op_id", sa.String(length=128), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column(
            "reason_codes", sa.String(length=2048), nullable=False, server_default=""
        ),
        sa.Column(
            "obligations", sa.String(length=1024), nullable=False, server_default=""
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

    op.create_table(
        "approvals",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("proposal_token", sa.String(length=64), nullable=False),
        sa.Column("policy_regime_id", ulid_domain_type(schema), nullable=False),
        sa.Column("op_id", sa.String(length=128), nullable=False),
        sa.Column("op_version", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=26), nullable=False),
        sa.Column("invocation_id", sa.String(length=26), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "clarification_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("proposal_token", name="uq_approvals_proposal_token"),
        schema=schema,
    )

    op.create_table(
        "policy_dedupe_logs",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("envelope_id", sa.String(length=26), nullable=False),
        sa.Column("trace_id", sa.String(length=26), nullable=False),
        sa.Column("denied", sa.Boolean(), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )


def downgrade() -> None:
    """Drop Policy authoritative schema objects."""
    schema = _schema()

    op.drop_table("policy_dedupe_logs", schema=schema)
    op.drop_table("approvals", schema=schema)
    op.drop_table("policy_decisions", schema=schema)
    op.drop_table("active_policy_regime", schema=schema)
    op.drop_table("policy_regimes", schema=schema)
