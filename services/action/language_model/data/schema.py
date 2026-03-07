"""Table models for Language Model Service provider call audits."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, Integer, MetaData, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB

from packages.brain_shared.ids import ulid_primary_key_column
from services.action.language_model.data.runtime import language_model_postgres_schema

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
    Column("finish_reason", String(64), nullable=False, server_default=""),
    Column("error_message", String(4096), nullable=False, server_default=""),
    Column("request_json", JSONB(astext_type=String()), nullable=True),
    Column("response_json", JSONB(astext_type=String()), nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)
