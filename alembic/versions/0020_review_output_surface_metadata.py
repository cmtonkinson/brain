"""Add review output criteria metadata and execution linkage.

Revision ID: 0020_review_output_surface_metadata
Revises: bdd7c89f9c03
Create Date: 2026-01-22 09:15:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0020_review_output_surface_metadata"
down_revision = "bdd7c89f9c03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_outputs",
        sa.Column("orphan_grace_period_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "review_outputs",
        sa.Column("consecutive_failure_threshold", sa.Integer(), nullable=True),
    )
    op.add_column(
        "review_outputs",
        sa.Column("stale_failure_age_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "review_outputs",
        sa.Column("ignored_pause_age_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "review_items",
        sa.Column("execution_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_review_items_execution_id",
        "review_items",
        "executions",
        ["execution_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_review_items_execution_id", "review_items", type_="foreignkey")
    op.drop_column("review_items", "execution_id")
    op.drop_column("review_outputs", "ignored_pause_age_seconds")
    op.drop_column("review_outputs", "stale_failure_age_seconds")
    op.drop_column("review_outputs", "consecutive_failure_threshold")
    op.drop_column("review_outputs", "orphan_grace_period_seconds")
