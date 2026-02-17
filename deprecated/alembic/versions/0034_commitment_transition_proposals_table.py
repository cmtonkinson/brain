"""Create commitment transition proposals table.

Revision ID: 0034_commitment_transition_proposals_table
Revises: 0033_commitment_review_runs_table
Create Date: 2026-02-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0034_commitment_transition_proposals_table"
down_revision = "0033_commitment_review_runs_table"
branch_labels = None
depends_on = None


_DEFERRABLE_STATES = ("OPEN", "COMPLETED", "MISSED", "CANCELED")
_DEFERRABLE_ACTORS = ("user", "system")
_DEFERRABLE_STATUSES = ("pending", "approved", "rejected", "canceled")


def upgrade() -> None:
    """Create commitment_transition_proposals table."""
    op.create_table(
        "commitment_transition_proposals",
        sa.Column(
            "proposal_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column(
            "commitment_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("commitments.commitment_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_state", sa.String(length=20), nullable=False),
        sa.Column("to_state", sa.String(length=20), nullable=False),
        sa.Column("actor", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=20), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "provenance_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("provenance_records.id"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "from_state IN %s" % (str(_DEFERRABLE_STATES),),
            name="ck_commitment_transition_proposals_from_state",
        ),
        sa.CheckConstraint(
            "to_state IN %s" % (str(_DEFERRABLE_STATES),),
            name="ck_commitment_transition_proposals_to_state",
        ),
        sa.CheckConstraint(
            "actor IN %s" % (str(_DEFERRABLE_ACTORS),),
            name="ck_commitment_transition_proposals_actor",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.00 AND confidence <= 1.00)",
            name="ck_commitment_transition_proposals_confidence",
        ),
        sa.CheckConstraint(
            "status IN %s" % (str(_DEFERRABLE_STATUSES),),
            name="ck_commitment_transition_proposals_status",
        ),
    )
    op.create_index(
        "ix_commitment_transition_proposals_commitment_status",
        "commitment_transition_proposals",
        ["commitment_id", "status", "proposed_at"],
    )
    op.create_index(
        "ix_commitment_transition_proposals_status",
        "commitment_transition_proposals",
        ["status", "proposed_at"],
    )


def downgrade() -> None:
    """Drop commitment_transition_proposals table."""
    op.drop_index(
        "ix_commitment_transition_proposals_status",
        table_name="commitment_transition_proposals",
    )
    op.drop_index(
        "ix_commitment_transition_proposals_commitment_status",
        table_name="commitment_transition_proposals",
    )
    op.drop_table("commitment_transition_proposals")
