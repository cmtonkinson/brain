"""SQLAlchemy table definitions owned by Memory Authority Service."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects import postgresql

from packages.brain_shared.ids import ULID_DOMAIN_NAME, ulid_primary_key_column
from services.state.memory_authority.data.runtime import memory_postgres_schema

metadata = MetaData()


def _ulid_domain() -> postgresql.DOMAIN:
    """Return schema-local ``ulid_bin`` domain reference."""
    return postgresql.DOMAIN(
        name=ULID_DOMAIN_NAME,
        data_type=postgresql.BYTEA(),
        schema=memory_postgres_schema(),
        create_type=False,
    )


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
    Column(
        "dialogue_start_turn_id",
        _ulid_domain(),
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
)

turns = Table(
    "turn",
    metadata,
    ulid_primary_key_column("id", schema_name=memory_postgres_schema()),
    Column(
        "session_id",
        _ulid_domain(),
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
    Column("principal", String(128), nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    CheckConstraint(
        "token_count IS NULL OR token_count >= 0",
        name="ck_turn_token_count_nonnegative",
    ),
)

turn_summaries = Table(
    "turn_summary",
    metadata,
    ulid_primary_key_column("id", schema_name=memory_postgres_schema()),
    Column(
        "session_id",
        _ulid_domain(),
        ForeignKey(f"{memory_postgres_schema()}.session.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "start_turn_id",
        _ulid_domain(),
        ForeignKey(f"{memory_postgres_schema()}.turn.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "end_turn_id",
        _ulid_domain(),
        ForeignKey(f"{memory_postgres_schema()}.turn.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("content", Text, nullable=False),
    Column("token_count", Integer, nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    UniqueConstraint(
        "session_id",
        "start_turn_id",
        "end_turn_id",
        name="uq_turn_summary_session_range",
    ),
    CheckConstraint("token_count >= 0", name="ck_turn_summary_token_count_nonnegative"),
)

Index("ix_turn_session_created", turns.c.session_id, turns.c.created_at)
Index(
    "ix_turn_summary_session_created",
    turn_summaries.c.session_id,
    turn_summaries.c.created_at,
)
