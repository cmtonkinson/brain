"""create delegation invocation table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from lib.shared.ids import ulid_domain_type
from services.reason.delegation.data.runtime import delegation_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260425_0001"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical Delegation-owned schema name."""
    return delegation_postgres_schema()


def upgrade() -> None:
    """Create Delegation authoritative schema objects."""
    schema = _schema()

    op.create_table(
        "invocation",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("parent_invocation_id", ulid_domain_type(schema), nullable=True),
        sa.Column(
            "depth",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("cancel_reason", sa.String(length=64), nullable=True),
        sa.Column("principal", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("personality_id", sa.String(length=128), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("context_text", sa.Text(), nullable=True),
        sa.Column(
            "context_object_refs",
            postgresql.JSONB(none_as_null=True),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "tool_allowlist",
            postgresql.JSONB(none_as_null=True),
            nullable=True,
        ),
        sa.Column("max_turns", sa.Integer(), nullable=False),
        sa.Column("budget_tokens", sa.BigInteger(), nullable=True),
        sa.Column("max_wallclock_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "tokens_in",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "tokens_out",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "turn_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("final_response", sa.Text(), nullable=True),
        sa.Column("transcript_ref", sa.Text(), nullable=True),
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "depth >= 0",
            name="ck_invocation_depth_nonnegative",
        ),
        sa.CheckConstraint(
            "max_turns > 0",
            name="ck_invocation_max_turns_positive",
        ),
        sa.CheckConstraint(
            "budget_tokens IS NULL OR budget_tokens > 0",
            name="ck_invocation_budget_tokens_positive",
        ),
        sa.CheckConstraint(
            "max_wallclock_seconds IS NULL OR max_wallclock_seconds > 0",
            name="ck_invocation_max_wallclock_positive",
        ),
        sa.CheckConstraint(
            "tokens_in >= 0",
            name="ck_invocation_tokens_in_nonnegative",
        ),
        sa.CheckConstraint(
            "tokens_out >= 0",
            name="ck_invocation_tokens_out_nonnegative",
        ),
        sa.CheckConstraint(
            "turn_count >= 0",
            name="ck_invocation_turn_count_nonnegative",
        ),
        schema=schema,
    )

    op.create_index(
        "ix_invocation_status_created_at",
        "invocation",
        ["status", "created_at"],
        schema=schema,
    )
    op.create_index(
        "ix_invocation_parent",
        "invocation",
        ["parent_invocation_id"],
        schema=schema,
    )


def downgrade() -> None:
    """Drop Delegation schema objects."""
    schema = _schema()
    op.drop_index("ix_invocation_parent", table_name="invocation", schema=schema)
    op.drop_index(
        "ix_invocation_status_created_at",
        table_name="invocation",
        schema=schema,
    )
    op.drop_table("invocation", schema=schema)
