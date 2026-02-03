"""Create commitment schedule linking table.

Revision ID: 0031_commitment_schedules_table
Revises: 0030_commitment_state_transitions
Create Date: 2026-02-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0031_commitment_schedules_table"
down_revision = "0030_commitment_state_transitions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create commitment_schedules table with composite primary key and indexes."""
    op.create_table(
        "commitment_schedules",
        sa.Column("commitment_id", sa.BigInteger(), nullable=False),
        sa.Column("schedule_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.PrimaryKeyConstraint("commitment_id", "schedule_id", name="pk_commitment_schedules"),
        sa.ForeignKeyConstraint(
            ["commitment_id"],
            ["commitments.commitment_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["schedules.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_commitment_schedules_schedule_id_active",
        "commitment_schedules",
        ["schedule_id"],
        postgresql_where=sa.text("is_active IS TRUE"),
    )
    op.create_index(
        "ix_commitment_schedules_commitment_id_active",
        "commitment_schedules",
        ["commitment_id"],
        postgresql_where=sa.text("is_active IS TRUE"),
    )


def downgrade() -> None:
    """Drop commitment_schedules table and indexes."""
    op.drop_index(
        "ix_commitment_schedules_commitment_id_active",
        table_name="commitment_schedules",
    )
    op.drop_index(
        "ix_commitment_schedules_schedule_id_active",
        table_name="commitment_schedules",
    )
    op.drop_table("commitment_schedules")
