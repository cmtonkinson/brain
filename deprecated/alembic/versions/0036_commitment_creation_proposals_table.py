"""Create commitment creation proposal table.

Revision ID: 0036_commitment_creation_proposals_table
Revises: 78b62e7a6968
Create Date: 2026-02-10 15:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0036_commitment_creation_proposals_table"
down_revision = "78b62e7a6968"
branch_labels = None
depends_on = None


_CREATION_PROPOSAL_KINDS = ("dedupe", "approval")
_CREATION_PROPOSAL_STATUSES = ("pending", "approved", "rejected", "canceled")


def upgrade() -> None:
    """Create commitment_creation_proposals table."""
    op.create_table(
        "commitment_creation_proposals",
        sa.Column("proposal_ref", sa.String(length=120), primary_key=True),
        sa.Column("proposal_kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("source_channel", sa.String(length=50), nullable=False),
        sa.Column("source_actor", sa.String(length=200), nullable=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=200), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_commitment_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("commitments.commitment_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "proposal_kind IN %s" % (str(_CREATION_PROPOSAL_KINDS),),
            name="ck_commitment_creation_proposals_kind",
        ),
        sa.CheckConstraint(
            "status IN %s" % (str(_CREATION_PROPOSAL_STATUSES),),
            name="ck_commitment_creation_proposals_status",
        ),
    )
    op.create_index(
        "ix_commitment_creation_proposals_status",
        "commitment_creation_proposals",
        ["status", "proposed_at"],
    )
    op.create_index(
        "ix_commitment_creation_proposals_channel_status",
        "commitment_creation_proposals",
        ["source_channel", "status", "proposed_at"],
    )


def downgrade() -> None:
    """Drop commitment_creation_proposals table."""
    op.drop_index(
        "ix_commitment_creation_proposals_channel_status",
        table_name="commitment_creation_proposals",
    )
    op.drop_index(
        "ix_commitment_creation_proposals_status",
        table_name="commitment_creation_proposals",
    )
    op.drop_table("commitment_creation_proposals")
