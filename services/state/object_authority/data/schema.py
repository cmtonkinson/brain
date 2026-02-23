"""SQLAlchemy table definitions owned by Object Authority Service."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
)

from packages.brain_shared.ids import ulid_primary_key_column
from services.state.object_authority.data.runtime import object_postgres_schema

metadata = MetaData()

objects = Table(
    "objects",
    metadata,
    ulid_primary_key_column("id", schema_name=object_postgres_schema()),
    Column("object_key", String(128), nullable=False),
    Column("digest_algorithm", String(32), nullable=False),
    Column("digest_version", String(16), nullable=False),
    Column("digest_hex", String(64), nullable=False),
    Column("extension", String(32), nullable=False),
    Column("content_type", String(256), nullable=False, server_default=""),
    Column("size_bytes", Integer, nullable=False),
    Column("original_filename", String(512), nullable=False, server_default=""),
    Column("source_uri", String(1024), nullable=False, server_default=""),
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
    UniqueConstraint("object_key", name="uq_objects_object_key"),
    UniqueConstraint(
        "digest_version",
        "digest_algorithm",
        "digest_hex",
        name="uq_objects_digest_identity",
    ),
    CheckConstraint("char_length(digest_hex) = 64", name="ck_objects_digest_len"),
    CheckConstraint("size_bytes >= 0", name="ck_objects_size_nonnegative"),
)
