"""SQLAlchemy table definitions owned by Recall Service."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    BigInteger,
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
from services.reason.recall.data.runtime import memory_postgres_schema

metadata = MetaData()


def _direction_enum() -> postgresql.ENUM:
    """Return schema-local turn direction enum reference."""
    return postgresql.ENUM(
        "inbound",
        "outbound",
        name="turn_direction",
        schema=memory_postgres_schema(),
        create_type=False,
    )


sessions = Table(
    "session",
    metadata,
    ulid_primary_key_column("id", schema_name=memory_postgres_schema()),
    Column("focus", Text, nullable=True),
    Column("focus_token_count", Integer, nullable=True),
    Column("dialogue_summary", Text, nullable=True),
    Column("dialogue_summary_token_count", Integer, nullable=True),
    Column("current_conversation_episode_id", String(26), nullable=True),
    Column("last_episode_inbound_at", DateTime(timezone=True), nullable=True),
    Column(
        "dialogue_start_turn_id",
        ulid_domain_type(memory_postgres_schema()),
        ForeignKey(
            f"{memory_postgres_schema()}.turn.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_session_dialogue_start_turn",
        ),
        nullable=True,
    ),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
    CheckConstraint(
        "focus_token_count IS NULL OR focus_token_count >= 0",
        name="ck_session_focus_token_count_nonnegative",
    ),
    CheckConstraint(
        "dialogue_summary_token_count IS NULL OR dialogue_summary_token_count >= 0",
        name="ck_session_dialogue_summary_token_count_nonnegative",
    ),
)

turns = Table(
    "turn",
    metadata,
    ulid_primary_key_column("id", schema_name=memory_postgres_schema()),
    Column(
        "session_id",
        ulid_domain_type(memory_postgres_schema()),
        ForeignKey(f"{memory_postgres_schema()}.session.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("direction", _direction_enum(), nullable=False),
    Column("content", Text, nullable=False),
    Column("role", String(64), nullable=False),
    Column("model", String(256), nullable=True),
    Column("provider", String(128), nullable=True),
    Column("token_count", Integer, nullable=True),
    Column("reasoning_level", String(64), nullable=True),
    Column("trace_id", String(64), nullable=False),
    Column("conversation_episode_id", String(26), nullable=False, server_default=""),
    Column("principal", String(128), nullable=False),
    Column("source", String(128), nullable=True),
    Column("sender_e164", String(32), nullable=True),
    Column("timestamp_ms", BigInteger, nullable=True),
    Column("source_device", String(128), nullable=True),
    Column("group_id", String(128), nullable=True),
    Column("quote_target_timestamp_ms", BigInteger, nullable=True),
    Column("reaction_target_timestamp_ms", BigInteger, nullable=True),
    Column("reaction_emoji", String(32), nullable=True),
    Column("approval_intent", String(64), nullable=True),
    Column("reply_to_proposal_token", String(128), nullable=True),
    Column("reaction_to_proposal_token", String(128), nullable=True),
    Column("delivery_state", String(32), nullable=True),
    Column("delivery_timestamp_ms", BigInteger, nullable=True),
    Column("delivery_detail", Text, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    CheckConstraint(
        "token_count IS NULL OR token_count >= 0",
        name="ck_turn_token_count_nonnegative",
    ),
    CheckConstraint(
        "timestamp_ms IS NULL OR timestamp_ms >= 0",
        name="ck_turn_timestamp_ms_nonnegative",
    ),
    CheckConstraint(
        "delivery_timestamp_ms IS NULL OR delivery_timestamp_ms >= 0",
        name="ck_turn_delivery_timestamp_ms_nonnegative",
    ),
    CheckConstraint(
        "delivery_state IS NULL OR delivery_state IN ('candidate', 'delivered', 'failed')",
        name="ck_turn_delivery_state_valid",
    ),
)

Index("ix_turn_session_created", turns.c.session_id, turns.c.created_at)
