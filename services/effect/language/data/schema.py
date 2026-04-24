"""Table models for Language Service provider call audits."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from lib.shared.ids import ulid_primary_key_column
from services.effect.language.data.runtime import language_model_postgres_schema

metadata = MetaData()

call_audits = Table(
    "call_audits",
    metadata,
    ulid_primary_key_column("id", schema_name=language_model_postgres_schema()),
    Column("envelope_id", String(26), nullable=False),
    Column("trace_id", String(26), nullable=False),
    Column("parent_id", String(26), nullable=False, server_default=""),
    Column("source", String(128), nullable=False),
    Column("principal", String(128), nullable=False),
    Column("provider", String(128), nullable=False),
    Column("model", String(256), nullable=False),
    Column("profile", String(32), nullable=False),
    Column("operation", String(32), nullable=False),
    Column("request_phase", String(32), nullable=False),
    Column("outcome_kind", String(32), nullable=False),
    Column("call_index", Integer, nullable=False),
    Column("duration_ms", Float, nullable=True),
    Column("finish_reason", String(64), nullable=True),
    Column("error_message", String(4096), nullable=True),
    Column("request_json", JSONB(astext_type=String()), nullable=True),
    Column("response_json", JSONB(astext_type=String()), nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

turn_cache_hops = Table(
    "turn_cache_hops",
    metadata,
    ulid_primary_key_column("id", schema_name=language_model_postgres_schema()),
    Column("trace_id", String(64), nullable=False),
    Column("hop_ordinal", Integer, nullable=False),
    Column("call_index", Integer, nullable=False),
    Column("envelope_id", String(26), nullable=False),
    Column("provider", String(128), nullable=False),
    Column("model", String(256), nullable=False),
    Column("profile", String(32), nullable=False),
    Column("placed_cachepoint_ordinal", Integer, nullable=True),
    Column("cp0_active", Boolean, nullable=False),
    Column("cp1_active", Boolean, nullable=False),
    Column("cp2_active", Boolean, nullable=False),
    Column("cp3_active", Boolean, nullable=False),
    Column("active_cachepoint_count", Integer, nullable=False),
    Column("provider_cache_control_block_count", Integer, nullable=False),
    Column("cache_creation_input_tokens", Integer, nullable=False),
    Column("cache_read_input_tokens", Integer, nullable=False),
    Column(
        "estimated_write_premium_token_equiv",
        Numeric(18, 4),
        nullable=False,
    ),
    Column(
        "estimated_read_savings_token_equiv",
        Numeric(18, 4),
        nullable=False,
    ),
    Column(
        "estimated_net_token_equiv",
        Numeric(18, 4),
        nullable=False,
    ),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    UniqueConstraint("trace_id", "hop_ordinal", name="uq_turn_cache_hops_trace_hop"),
)
