"""Table models for Policy Service regimes, decisions, and approvals."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    func,
)

from packages.brain_shared.ids import ulid_primary_key_column
from services.action.policy_service.component import SERVICE_COMPONENT_ID

metadata = MetaData()

policy_regimes = Table(
    "policy_regimes",
    metadata,
    ulid_primary_key_column("id", schema_name=str(SERVICE_COMPONENT_ID)),
    Column("policy_hash", String(64), nullable=False, unique=True),
    Column("policy_json", String, nullable=False),
    Column("policy_id", String(128), nullable=False),
    Column("policy_version", String(64), nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

active_policy_regime = Table(
    "active_policy_regime",
    metadata,
    Column("pointer_id", String(16), primary_key=True),
    Column(
        "policy_regime_id",
        String(26),
        ForeignKey(f"{SERVICE_COMPONENT_ID}.policy_regimes.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

policy_decisions = Table(
    "policy_decisions",
    metadata,
    ulid_primary_key_column("id", schema_name=str(SERVICE_COMPONENT_ID)),
    Column("policy_regime_id", String(26), nullable=False),
    Column("envelope_id", String(26), nullable=False),
    Column("trace_id", String(26), nullable=False),
    Column("actor", String(128), nullable=False),
    Column("channel", String(128), nullable=False),
    Column("capability_id", String(128), nullable=False),
    Column("allowed", Boolean, nullable=False),
    Column("reason_codes", String(2048), nullable=False, server_default=""),
    Column("obligations", String(1024), nullable=False, server_default=""),
    Column("proposal_token", String(64), nullable=False, server_default=""),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

approvals = Table(
    "approvals",
    metadata,
    ulid_primary_key_column("id", schema_name=str(SERVICE_COMPONENT_ID)),
    Column("proposal_token", String(64), nullable=False, unique=True),
    Column("policy_regime_id", String(26), nullable=False),
    Column("capability_id", String(128), nullable=False),
    Column("capability_version", String(32), nullable=False),
    Column("summary", String(512), nullable=False),
    Column("actor", String(128), nullable=False),
    Column("channel", String(128), nullable=False),
    Column("trace_id", String(26), nullable=False),
    Column("invocation_id", String(26), nullable=False),
    Column("status", String(32), nullable=False),
    Column("clarification_attempts", Integer, nullable=False, server_default="0"),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

policy_dedupe_logs = Table(
    "policy_dedupe_logs",
    metadata,
    ulid_primary_key_column("id", schema_name=str(SERVICE_COMPONENT_ID)),
    Column("dedupe_key", String(64), nullable=False),
    Column("envelope_id", String(26), nullable=False),
    Column("trace_id", String(26), nullable=False),
    Column("denied", Boolean, nullable=False),
    Column("window_seconds", Integer, nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)
