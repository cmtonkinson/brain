"""add foreign key constraints to ingestion service tables"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from lib.shared.ids import ulid_domain_type
from services.reason.ingestion.data.runtime import ingestion_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260420_0002"
down_revision = "20260418_0001"
branch_labels = None
depends_on = None


def _schema() -> str:
    return ingestion_postgres_schema()


def upgrade() -> None:
    """Create ingestion_indexing_runs table and add referential integrity constraints."""
    schema = _schema()

    op.create_table(
        "ingestion_indexing_runs",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("ingestion_id", sa.LargeBinary(16), nullable=False),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.create_index(
        "ix_indexing_runs_ingestion_id",
        "ingestion_indexing_runs",
        ["ingestion_id"],
        schema=schema,
    )
    op.create_index(
        "ix_indexing_runs_status",
        "ingestion_indexing_runs",
        ["status"],
        schema=schema,
    )

    op.create_foreign_key(
        "fk_stage_runs_ingestion_id",
        "ingestion_stage_runs",
        "ingestions",
        ["ingestion_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_outcomes_ingestion_id",
        "stage_artifact_outcomes",
        "ingestions",
        ["ingestion_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_prov_sources_provenance_id",
        "provenance_sources",
        "artifact_provenance",
        ["provenance_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_prov_sources_ingestion_id",
        "provenance_sources",
        "ingestions",
        ["ingestion_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_anchor_notes_ingestion_id",
        "anchor_notes",
        "ingestions",
        ["ingestion_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_indexing_runs_ingestion_id",
        "ingestion_indexing_runs",
        "ingestions",
        ["ingestion_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Drop foreign key constraints."""
    schema = _schema()

    op.drop_constraint(
        "fk_indexing_runs_ingestion_id",
        "ingestion_indexing_runs",
        schema=schema,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_anchor_notes_ingestion_id",
        "anchor_notes",
        schema=schema,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_prov_sources_ingestion_id",
        "provenance_sources",
        schema=schema,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_prov_sources_provenance_id",
        "provenance_sources",
        schema=schema,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_outcomes_ingestion_id",
        "stage_artifact_outcomes",
        schema=schema,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_stage_runs_ingestion_id",
        "ingestion_stage_runs",
        schema=schema,
        type_="foreignkey",
    )
    op.drop_table("ingestion_indexing_runs", schema=schema)
