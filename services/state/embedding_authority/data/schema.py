"""SQLAlchemy table definitions owned by Embedding Authority Service."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from packages.brain_shared.ids import ulid_primary_key_column
from services.state.embedding_authority.data.runtime import embedding_postgres_schema

metadata = MetaData()

specs = Table(
    "specs",
    metadata,
    ulid_primary_key_column("id", schema_name=embedding_postgres_schema()),
    Column("provider", String(128), nullable=False),
    Column("name", String(256), nullable=False),
    Column("version", String(64), nullable=False),
    Column("dimensions", Integer, nullable=False),
    Column("canonical_string", String(512), nullable=False),
    Column("hash", LargeBinary(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
    UniqueConstraint("hash", name="uq_specs_hash"),
    CheckConstraint("dimensions > 0", name="ck_specs_dimensions_positive"),
)

sources = Table(
    "sources",
    metadata,
    ulid_primary_key_column("id", schema_name=embedding_postgres_schema()),
    Column("source_type", String(128), nullable=False),
    Column("canonical_reference", String(1024), nullable=False),
    Column("service", String(128), nullable=False),
    Column("principal", String(128), nullable=False),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
    UniqueConstraint(
        "canonical_reference",
        "service",
        "principal",
        name="uq_sources_reference_service_principal",
    ),
)

chunks = Table(
    "chunks",
    metadata,
    ulid_primary_key_column("id", schema_name=embedding_postgres_schema()),
    Column(
        "source_id",
        LargeBinary(16),
        ForeignKey(f"{embedding_postgres_schema()}.sources.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("chunk_ordinal", Integer, nullable=False),
    Column("reference_range", String(256), nullable=False, server_default=""),
    Column("content_hash", String(128), nullable=False),
    Column("text", String, nullable=False),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
    UniqueConstraint("source_id", "chunk_ordinal", name="uq_chunks_source_ordinal"),
)

embeddings = Table(
    "embeddings",
    metadata,
    Column(
        "chunk_id",
        LargeBinary(16),
        ForeignKey(f"{embedding_postgres_schema()}.chunks.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "spec_id",
        LargeBinary(16),
        ForeignKey(f"{embedding_postgres_schema()}.specs.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("content_hash", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("error_detail", String(1024), nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
    PrimaryKeyConstraint("chunk_id", "spec_id", name="pk_embeddings_chunk_spec"),
)

Index("ix_sources_canonical_reference", sources.c.canonical_reference)
Index("ix_sources_service", sources.c.service)
Index("ix_sources_principal", sources.c.principal)

Index("ix_chunks_source_id", chunks.c.source_id)
Index("ix_chunks_content_hash", chunks.c.content_hash)

Index("ix_embeddings_spec_id", embeddings.c.spec_id)
Index("ix_embeddings_status", embeddings.c.status)
