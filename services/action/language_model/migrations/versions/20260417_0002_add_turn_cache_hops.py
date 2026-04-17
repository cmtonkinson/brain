"""add turn cache telemetry tables and view"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from packages.brain_shared.ids.constants import ULID_DOMAIN_NAME
from services.action.language_model.data.runtime import language_model_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260417_0002"
down_revision = "20260307_0001"
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical LMS-owned schema name."""
    return language_model_postgres_schema()


def _ulid_domain(schema: str) -> postgresql.DOMAIN:
    """Return schema-local ``ulid_bin`` domain reference."""
    return postgresql.DOMAIN(
        name=ULID_DOMAIN_NAME,
        data_type=postgresql.BYTEA(),
        schema=schema,
        create_type=False,
    )


def upgrade() -> None:
    """Create LMS-owned turn cache telemetry schema objects."""
    schema = _schema()
    op.create_table(
        "turn_cache_hops",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("hop_ordinal", sa.Integer(), nullable=False),
        sa.Column("call_index", sa.Integer(), nullable=False),
        sa.Column("envelope_id", sa.String(length=26), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("profile", sa.String(length=32), nullable=False),
        sa.Column("placed_cachepoint_ordinal", sa.Integer(), nullable=True),
        sa.Column("cp0_active", sa.Boolean(), nullable=False),
        sa.Column("cp1_active", sa.Boolean(), nullable=False),
        sa.Column("cp2_active", sa.Boolean(), nullable=False),
        sa.Column("cp3_active", sa.Boolean(), nullable=False),
        sa.Column("active_cachepoint_count", sa.Integer(), nullable=False),
        sa.Column("provider_cache_control_block_count", sa.Integer(), nullable=False),
        sa.Column("cache_creation_input_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_input_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "estimated_write_premium_token_equiv",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column(
            "estimated_read_savings_token_equiv",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column(
            "estimated_net_token_equiv",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "trace_id",
            "hop_ordinal",
            name="uq_turn_cache_hops_trace_hop",
        ),
        schema=schema,
    )
    op.create_index(
        "ix_turn_cache_hops_trace_call_index",
        "turn_cache_hops",
        ["trace_id", "call_index"],
        unique=False,
        schema=schema,
    )
    op.execute(
        sa.text(
            f"""
            CREATE VIEW {schema}.turn_cache_traces_v AS
            SELECT
                trace_id,
                COUNT(*)::integer AS hop_count,
                MIN(hop_ordinal) FILTER (WHERE placed_cachepoint_ordinal = 0)::integer AS cp0_placed_hop,
                MIN(hop_ordinal) FILTER (WHERE placed_cachepoint_ordinal = 1)::integer AS cp1_placed_hop,
                MIN(hop_ordinal) FILTER (WHERE placed_cachepoint_ordinal = 2)::integer AS cp2_placed_hop,
                MIN(hop_ordinal) FILTER (WHERE placed_cachepoint_ordinal = 3)::integer AS cp3_placed_hop,
                SUM(cache_creation_input_tokens)::bigint AS total_cache_creation_input_tokens,
                SUM(cache_read_input_tokens)::bigint AS total_cache_read_input_tokens,
                SUM(estimated_write_premium_token_equiv)::numeric(18,4) AS total_estimated_write_premium_token_equiv,
                SUM(estimated_read_savings_token_equiv)::numeric(18,4) AS total_estimated_read_savings_token_equiv,
                SUM(estimated_net_token_equiv)::numeric(18,4) AS total_estimated_net_token_equiv,
                MAX(active_cachepoint_count)::integer AS max_active_cachepoint_count,
                MIN(created_at) AS first_created_at,
                MAX(created_at) AS last_created_at
            FROM {schema}.turn_cache_hops
            GROUP BY trace_id
            """
        )
    )


def downgrade() -> None:
    """Drop LMS-owned turn cache telemetry schema objects."""
    schema = _schema()
    op.execute(sa.text(f"DROP VIEW IF EXISTS {schema}.turn_cache_traces_v"))
    op.drop_index(
        "ix_turn_cache_hops_trace_call_index",
        table_name="turn_cache_hops",
        schema=schema,
    )
    op.drop_table("turn_cache_hops", schema=schema)
