"""Add commitment review items and review delivery tracking.

Revision ID: 0035_commitment_review_items_table
Revises: 0034_commitment_transition_proposals_table
Create Date: 2026-02-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0035_commitment_review_items_table"
down_revision = "0034_commitment_transition_proposals_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add review delivery fields and review items table."""
    op.add_column(
        "commitment_review_runs",
        sa.Column("owner", sa.String(), nullable=True),
    )
    op.add_column(
        "commitment_review_runs",
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "commitment_review_runs",
        sa.Column("engaged_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "commitment_review_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "review_run_id",
            sa.Integer(),
            sa.ForeignKey("commitment_review_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "commitment_id",
            sa.BigInteger(),
            sa.ForeignKey("commitments.commitment_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "review_run_id",
            "commitment_id",
            name="uq_commitment_review_items_review_run_commitment",
        ),
    )
    op.create_index(
        "idx_commitment_review_items_review_run_id",
        "commitment_review_items",
        ["review_run_id"],
    )
    op.create_index(
        "idx_commitment_review_items_commitment_id",
        "commitment_review_items",
        ["commitment_id"],
    )


def downgrade() -> None:
    """Drop review items table and delivery fields."""
    op.drop_index(
        "idx_commitment_review_items_commitment_id",
        table_name="commitment_review_items",
    )
    op.drop_index(
        "idx_commitment_review_items_review_run_id",
        table_name="commitment_review_items",
    )
    op.drop_table("commitment_review_items")
    op.drop_column("commitment_review_runs", "engaged_at")
    op.drop_column("commitment_review_runs", "delivered_at")
    op.drop_column("commitment_review_runs", "owner")
