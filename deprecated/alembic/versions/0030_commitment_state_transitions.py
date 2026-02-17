"""Create commitment state transitions audit table.

Revision ID: 0030_commitment_state_transitions
Revises: 0029_commitments_table
Create Date: 2026-02-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0030_commitment_state_transitions"
down_revision = "0029_commitments_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create commitment_state_transitions table with constraints and indexes."""
    state_enum = sa.Enum(
        "OPEN",
        "COMPLETED",
        "MISSED",
        "CANCELED",
        name="commitment_state",
        native_enum=False,
    )
    actor_enum = sa.Enum(
        "user",
        "system",
        name="commitment_transition_actor",
        native_enum=False,
    )
    op.create_table(
        "commitment_state_transitions",
        sa.Column("transition_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "commitment_id",
            sa.BigInteger(),
            sa.ForeignKey("commitments.commitment_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_state", state_enum, nullable=False),
        sa.Column("to_state", state_enum, nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", actor_enum, nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "provenance_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("provenance_records.id"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "from_state IN ('OPEN', 'COMPLETED', 'MISSED', 'CANCELED')",
            name="ck_commitment_state_transitions_from_state",
        ),
        sa.CheckConstraint(
            "to_state IN ('OPEN', 'COMPLETED', 'MISSED', 'CANCELED')",
            name="ck_commitment_state_transitions_to_state",
        ),
        sa.CheckConstraint(
            "actor IN ('user', 'system')",
            name="ck_commitment_state_transitions_actor",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.00 AND confidence <= 1.00)",
            name="ck_commitment_state_transitions_confidence",
        ),
    )
    op.create_index(
        "ix_commitment_state_transitions_commitment_id",
        "commitment_state_transitions",
        ["commitment_id", "transitioned_at"],
    )
    op.create_index(
        "ix_commitment_state_transitions_to_state",
        "commitment_state_transitions",
        ["to_state", "transitioned_at"],
    )
    op.create_index(
        "ix_commitment_state_transitions_actor",
        "commitment_state_transitions",
        ["actor", "transitioned_at"],
    )
    op.create_index(
        "ix_commitment_state_transitions_confidence",
        "commitment_state_transitions",
        ["confidence"],
        postgresql_where=sa.text("confidence IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop commitment_state_transitions table and indexes."""
    op.drop_index(
        "ix_commitment_state_transitions_confidence",
        table_name="commitment_state_transitions",
    )
    op.drop_index(
        "ix_commitment_state_transitions_actor",
        table_name="commitment_state_transitions",
    )
    op.drop_index(
        "ix_commitment_state_transitions_to_state",
        table_name="commitment_state_transitions",
    )
    op.drop_index(
        "ix_commitment_state_transitions_commitment_id",
        table_name="commitment_state_transitions",
    )
    op.drop_table("commitment_state_transitions")
