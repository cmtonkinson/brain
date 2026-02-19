"""SQLAlchemy schema objects owned by the Embedding Authority Service."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, MetaData, String, Table, func

from packages.brain_shared.ids import ulid_primary_key_column
from services.state.embedding_authority.data.runtime import embedding_postgres_schema

EMBEDDING_AUDIT_TABLE_NAME = "embedding_audit_log"

metadata = MetaData()

embedding_audit_log = Table(
    EMBEDDING_AUDIT_TABLE_NAME,
    metadata,
    ulid_primary_key_column("id", schema_name=embedding_postgres_schema()),
    Column(
        "occurred_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("envelope_id", String(64), nullable=False),
    Column("trace_id", String(64), nullable=False),
    Column("principal", String(128), nullable=False),
    Column("operation", String(64), nullable=False),
    Column("namespace", String(256), nullable=False),
    Column("key", String(512), nullable=False),
    Column("model", String(256), nullable=False),
    Column("outcome", String(64), nullable=False),
    Column("error_code", String(128), nullable=False, server_default=""),
)
