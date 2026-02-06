"""Create commitment_artifacts linkage table.

Revision ID: 0034_commitment_artifacts_table
Revises: 0033_commitment_progress_nullable_provenance
Create Date: 2026-02-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0034_commitment_artifacts_table"
down_revision = "0033_commitment_progress_nullable_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create commitment_artifacts junction table for related artifact linkage."""
    op.create_table(
        "commitment_artifacts",
        sa.Column("commitment_id", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("relationship_type", sa.Text(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("added_by", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["commitment_id"],
            ["commitments.commitment_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["object_key"],
            ["artifacts.object_key"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("commitment_id", "object_key"),
        sa.CheckConstraint(
            "relationship_type IN ('evidence', 'context', 'reference', 'progress', 'related')",
            name="ck_commitment_artifacts_relationship_type",
        ),
        sa.CheckConstraint(
            "added_by IN ('user', 'system')",
            name="ck_commitment_artifacts_added_by",
        ),
    )

    # Index for querying artifacts by commitment
    op.create_index(
        "ix_commitment_artifacts_commitment_id",
        "commitment_artifacts",
        ["commitment_id"],
    )

    # Index for reverse lookup (commitments by artifact)
    op.create_index(
        "ix_commitment_artifacts_object_key",
        "commitment_artifacts",
        ["object_key"],
    )


def downgrade() -> None:
    """Drop commitment_artifacts table and indexes."""
    op.drop_index("ix_commitment_artifacts_object_key", table_name="commitment_artifacts")
    op.drop_index("ix_commitment_artifacts_commitment_id", table_name="commitment_artifacts")
    op.drop_table("commitment_artifacts")
