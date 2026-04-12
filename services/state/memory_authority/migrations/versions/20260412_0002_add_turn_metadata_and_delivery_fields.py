"""add turn metadata and delivery fields"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from services.state.memory_authority.data.runtime import memory_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260412_0002"
down_revision = "20260224_0001"
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical MAS-owned schema name."""
    return memory_postgres_schema()


def upgrade() -> None:
    """Add inbound-instruction metadata and outbound delivery fields to turn rows."""
    schema = _schema()

    op.add_column(
        "turn",
        sa.Column("source", sa.String(length=128), nullable=True),
        schema=schema,
    )
    op.add_column(
        "turn",
        sa.Column("sender_e164", sa.String(length=32), nullable=True),
        schema=schema,
    )
    op.add_column(
        "turn",
        sa.Column("timestamp_ms", sa.BigInteger(), nullable=True),
        schema=schema,
    )
    op.add_column(
        "turn",
        sa.Column("source_device", sa.String(length=128), nullable=True),
        schema=schema,
    )
    op.add_column(
        "turn",
        sa.Column("group_id", sa.String(length=128), nullable=True),
        schema=schema,
    )
    op.add_column(
        "turn",
        sa.Column("quote_target_timestamp_ms", sa.BigInteger(), nullable=True),
        schema=schema,
    )
    op.add_column(
        "turn",
        sa.Column("reaction_target_timestamp_ms", sa.BigInteger(), nullable=True),
        schema=schema,
    )
    op.add_column(
        "turn",
        sa.Column("reaction_emoji", sa.String(length=32), nullable=True),
        schema=schema,
    )
    op.add_column(
        "turn",
        sa.Column("approval_intent", sa.String(length=64), nullable=True),
        schema=schema,
    )
    op.add_column(
        "turn",
        sa.Column("reply_to_proposal_token", sa.String(length=128), nullable=True),
        schema=schema,
    )
    op.add_column(
        "turn",
        sa.Column("reaction_to_proposal_token", sa.String(length=128), nullable=True),
        schema=schema,
    )
    op.add_column(
        "turn",
        sa.Column("delivery_state", sa.String(length=32), nullable=True),
        schema=schema,
    )
    op.add_column(
        "turn",
        sa.Column("delivery_timestamp_ms", sa.BigInteger(), nullable=True),
        schema=schema,
    )
    op.add_column(
        "turn",
        sa.Column("delivery_detail", sa.Text(), nullable=True),
        schema=schema,
    )

    op.create_check_constraint(
        "ck_turn_timestamp_ms_nonnegative",
        "turn",
        "timestamp_ms IS NULL OR timestamp_ms >= 0",
        schema=schema,
    )
    op.create_check_constraint(
        "ck_turn_delivery_timestamp_ms_nonnegative",
        "turn",
        "delivery_timestamp_ms IS NULL OR delivery_timestamp_ms >= 0",
        schema=schema,
    )
    op.create_check_constraint(
        "ck_turn_delivery_state_valid",
        "turn",
        "delivery_state IS NULL OR delivery_state IN ('candidate', 'delivered', 'failed')",
        schema=schema,
    )


def downgrade() -> None:
    """Drop inbound-instruction metadata and outbound delivery fields from turn rows."""
    schema = _schema()

    op.drop_constraint(
        "ck_turn_delivery_state_valid",
        "turn",
        schema=schema,
        type_="check",
    )
    op.drop_constraint(
        "ck_turn_delivery_timestamp_ms_nonnegative",
        "turn",
        schema=schema,
        type_="check",
    )
    op.drop_constraint(
        "ck_turn_timestamp_ms_nonnegative",
        "turn",
        schema=schema,
        type_="check",
    )

    for column_name in (
        "delivery_detail",
        "delivery_timestamp_ms",
        "delivery_state",
        "reaction_to_proposal_token",
        "reply_to_proposal_token",
        "approval_intent",
        "reaction_emoji",
        "reaction_target_timestamp_ms",
        "quote_target_timestamp_ms",
        "group_id",
        "source_device",
        "timestamp_ms",
        "sender_e164",
        "source",
    ):
        op.drop_column("turn", column_name, schema=schema)
