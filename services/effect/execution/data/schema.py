"""Table models for Execution state and invocation audits."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, String, Table, func

from lib.shared.ids import ulid_primary_key_column
from services.effect.execution.component import SERVICE_COMPONENT_ID

metadata = MetaData()

op_discovery_state = Table(
    "op_discovery_state",
    metadata,
    ulid_primary_key_column("id", schema_name=str(SERVICE_COMPONENT_ID)),
    Column("op_id", String(128), nullable=False, unique=True),
    Column("content_digest", String(64), nullable=False),
    Column("chunk_ordinal", Integer, nullable=False),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

dynamic_op_classifications = Table(
    "dynamic_op_classifications",
    metadata,
    ulid_primary_key_column("id", schema_name=str(SERVICE_COMPONENT_ID)),
    Column("op_id", String(128), nullable=False, unique=True),
    Column("source_kind", String(64), nullable=False),
    Column("source_ref", String(256), nullable=False),
    Column("definition_digest", String(64), nullable=False),
    Column("summary", String(2048), nullable=False, server_default=""),
    Column("input_schema_json", String, nullable=True),
    Column("output_schema_json", String, nullable=True),
    Column("effect", String(32), nullable=True),
    Column("approval", String(32), nullable=True),
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
    Column("op_id", String(128), nullable=False),
    Column("op_version", String(32), nullable=False),
    Column("policy_decision_id", String(26), nullable=False),
    Column("policy_regime_id", String(26), nullable=False),
    Column("allowed", Boolean, nullable=False),
    Column("reason_codes", String(2048), nullable=False, server_default=""),
    Column("proposal_token", String(64), nullable=False, server_default=""),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)
