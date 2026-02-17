"""Create commitments table for commitment tracking.

Revision ID: 0029_commitments_table
Revises: 0028_ingestion_stage_runs_table
Create Date: 2026-02-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0029_commitments_table"
down_revision = "0028_ingestion_stage_runs_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create commitments table with constraints and indexes."""
    state_enum = sa.Enum(
        "OPEN",
        "COMPLETED",
        "MISSED",
        "CANCELED",
        name="commitment_state",
        native_enum=False,
    )
    op.create_table(
        "commitments",
        sa.Column("commitment_id", sa.BigInteger(), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "provenance_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("provenance_records.id"),
            nullable=True,
        ),
        sa.Column(
            "state",
            state_enum,
            nullable=False,
            server_default="OPEN",
        ),
        sa.Column(
            "importance",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
        sa.Column(
            "effort_provided",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
        sa.Column("effort_inferred", sa.Integer(), nullable=True),
        sa.Column("urgency", sa.Integer(), nullable=True),
        sa.Column("due_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ever_missed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("presented_for_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "next_schedule_id",
            sa.Integer(),
            sa.ForeignKey("schedules.id"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "state IN ('OPEN', 'COMPLETED', 'MISSED', 'CANCELED')",
            name="ck_commitments_state",
        ),
        sa.CheckConstraint("importance BETWEEN 1 AND 3", name="ck_commitments_importance"),
        sa.CheckConstraint(
            "effort_provided BETWEEN 1 AND 3",
            name="ck_commitments_effort_provided",
        ),
    )
    op.create_index("ix_commitments_state", "commitments", ["state"])
    op.create_index("ix_commitments_due_by", "commitments", ["due_by"])
    op.create_index("ix_commitments_provenance_id", "commitments", ["provenance_id"])
    op.create_index("ix_commitments_next_schedule_id", "commitments", ["next_schedule_id"])


def downgrade() -> None:
    """Drop commitments table and indexes."""
    op.drop_index("ix_commitments_next_schedule_id", table_name="commitments")
    op.drop_index("ix_commitments_provenance_id", table_name="commitments")
    op.drop_index("ix_commitments_due_by", table_name="commitments")
    op.drop_index("ix_commitments_state", table_name="commitments")
    op.drop_table("commitments")
