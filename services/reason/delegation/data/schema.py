"""SQLAlchemy table definitions owned by Delegation Service."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects import postgresql

from lib.shared.ids import ulid_domain_type, ulid_primary_key_column
from services.reason.delegation.data.runtime import delegation_postgres_schema

metadata = MetaData()


invocations = Table(
    "invocation",
    metadata,
    ulid_primary_key_column("id", schema_name=delegation_postgres_schema()),
    Column(
        "parent_invocation_id",
        ulid_domain_type(delegation_postgres_schema()),
        nullable=True,
    ),
    Column("depth", Integer, nullable=False, server_default="0"),
    Column("status", String(length=32), nullable=False),
    Column("cancel_reason", String(length=64), nullable=True),
    Column("principal", String(length=128), nullable=False),
    Column("channel", String(length=64), nullable=False),
    Column("personality_id", String(length=128), nullable=False),
    Column("prompt", Text, nullable=False),
    Column("context_text", Text, nullable=True),
    Column(
        "context_object_refs",
        postgresql.JSONB(none_as_null=True),
        nullable=False,
        server_default="[]",
    ),
    Column("tool_allowlist", postgresql.JSONB(none_as_null=True), nullable=True),
    Column("max_turns", Integer, nullable=False),
    Column("budget_tokens", BigInteger, nullable=True),
    Column("max_wallclock_seconds", Integer, nullable=True),
    Column("tokens_in", BigInteger, nullable=False, server_default="0"),
    Column("tokens_out", BigInteger, nullable=False, server_default="0"),
    Column("turn_count", Integer, nullable=False, server_default="0"),
    Column("final_response", Text, nullable=True),
    Column("transcript_ref", Text, nullable=True),
    Column("claimed_by", String(length=128), nullable=True),
    Column("claimed_at", DateTime(timezone=True), nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
    CheckConstraint("depth >= 0", name="ck_invocation_depth_nonnegative"),
    CheckConstraint("max_turns > 0", name="ck_invocation_max_turns_positive"),
    CheckConstraint(
        "budget_tokens IS NULL OR budget_tokens > 0",
        name="ck_invocation_budget_tokens_positive",
    ),
    CheckConstraint(
        "max_wallclock_seconds IS NULL OR max_wallclock_seconds > 0",
        name="ck_invocation_max_wallclock_positive",
    ),
    CheckConstraint("tokens_in >= 0", name="ck_invocation_tokens_in_nonnegative"),
    CheckConstraint("tokens_out >= 0", name="ck_invocation_tokens_out_nonnegative"),
    CheckConstraint("turn_count >= 0", name="ck_invocation_turn_count_nonnegative"),
    Index("ix_invocation_status_created_at", "status", "created_at"),
    Index("ix_invocation_parent", "parent_invocation_id"),
)
