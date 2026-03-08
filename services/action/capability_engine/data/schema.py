"""Table models for Capability Engine state and invocation audits."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, String, Table, func

from packages.brain_shared.ids import ulid_primary_key_column
from services.action.capability_engine.component import SERVICE_COMPONENT_ID

metadata = MetaData()

capability_discovery_state = Table(
    "capability_discovery_state",
    metadata,
    ulid_primary_key_column("id", schema_name=str(SERVICE_COMPONENT_ID)),
    Column("capability_id", String(128), nullable=False, unique=True),
    Column("content_digest", String(64), nullable=False),
    Column("chunk_ordinal", Integer, nullable=False),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

invocation_audits = Table(
    "invocation_audits",
    metadata,
    ulid_primary_key_column("id", schema_name=str(SERVICE_COMPONENT_ID)),
    Column("envelope_id", String(26), nullable=False),
    Column("trace_id", String(26), nullable=False),
    Column("parent_id", String(26), nullable=False, server_default=""),
    Column("invocation_id", String(26), nullable=False),
    Column("parent_invocation_id", String(26), nullable=False, server_default=""),
    Column("actor", String(128), nullable=False),
    Column("source", String(128), nullable=False),
    Column("channel", String(128), nullable=False),
    Column("capability_id", String(128), nullable=False),
    Column("capability_version", String(32), nullable=False),
    Column("policy_decision_id", String(26), nullable=False),
    Column("policy_regime_id", String(26), nullable=False),
    Column("allowed", Boolean, nullable=False),
    Column("reason_codes", String(2048), nullable=False, server_default=""),
    Column("proposal_token", String(64), nullable=False, server_default=""),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)
