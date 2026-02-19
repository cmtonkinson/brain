"""create embedding authority tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from services.state.embedding_authority.data.runtime import embedding_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260218_0001"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve the canonical EAS-owned schema name."""
    return embedding_postgres_schema()


def _ulid_domain(schema: str) -> postgresql.DOMAIN:
    """Return schema-local ``ulid_bin`` domain reference."""
    return postgresql.DOMAIN(
        name="ulid_bin",
        data_type=postgresql.BYTEA(),
        schema=schema,
        create_type=False,
    )


def upgrade() -> None:
    """Create EAS authoritative schema objects."""
    schema = _schema()

    op.create_table(
        "specs",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("canonical_string", sa.String(length=512), nullable=False),
        sa.Column("hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("hash", name="uq_specs_hash"),
        sa.CheckConstraint("dimensions > 0", name="ck_specs_dimensions_positive"),
        schema=schema,
    )

    op.create_table(
        "sources",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("source_type", sa.String(length=128), nullable=False),
        sa.Column("canonical_reference", sa.String(length=1024), nullable=False),
        sa.Column("service", sa.String(length=128), nullable=False),
        sa.Column("principal", sa.String(length=128), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "canonical_reference",
            "service",
            "principal",
            name="uq_sources_reference_service_principal",
        ),
        schema=schema,
    )

    op.create_table(
        "chunks",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("source_id", _ulid_domain(schema), nullable=False),
        sa.Column("chunk_ordinal", sa.Integer(), nullable=False),
        sa.Column("reference_range", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_id"], [f"{schema}.sources.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("source_id", "chunk_ordinal", name="uq_chunks_source_ordinal"),
        schema=schema,
    )

    op.create_table(
        "embeddings",
        sa.Column("chunk_id", _ulid_domain(schema), nullable=False),
        sa.Column("spec_id", _ulid_domain(schema), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_detail", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["chunk_id"], [f"{schema}.chunks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["spec_id"], [f"{schema}.specs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("chunk_id", "spec_id", name="pk_embeddings_chunk_spec"),
        schema=schema,
    )

    op.create_index("ix_sources_canonical_reference", "sources", ["canonical_reference"], unique=False, schema=schema)
    op.create_index("ix_sources_service", "sources", ["service"], unique=False, schema=schema)
    op.create_index("ix_sources_principal", "sources", ["principal"], unique=False, schema=schema)

    op.create_index("ix_chunks_source_id", "chunks", ["source_id"], unique=False, schema=schema)
    op.create_index("ix_chunks_content_hash", "chunks", ["content_hash"], unique=False, schema=schema)

    op.create_index("ix_embeddings_spec_id", "embeddings", ["spec_id"], unique=False, schema=schema)
    op.create_index("ix_embeddings_status", "embeddings", ["status"], unique=False, schema=schema)


def downgrade() -> None:
    """Drop EAS authoritative schema objects."""
    schema = _schema()

    op.drop_index("ix_embeddings_status", table_name="embeddings", schema=schema)
    op.drop_index("ix_embeddings_spec_id", table_name="embeddings", schema=schema)

    op.drop_index("ix_chunks_content_hash", table_name="chunks", schema=schema)
    op.drop_index("ix_chunks_source_id", table_name="chunks", schema=schema)

    op.drop_index("ix_sources_principal", table_name="sources", schema=schema)
    op.drop_index("ix_sources_service", table_name="sources", schema=schema)
    op.drop_index("ix_sources_canonical_reference", table_name="sources", schema=schema)

    op.drop_table("embeddings", schema=schema)
    op.drop_table("chunks", schema=schema)
    op.drop_table("sources", schema=schema)
    op.drop_table("specs", schema=schema)
