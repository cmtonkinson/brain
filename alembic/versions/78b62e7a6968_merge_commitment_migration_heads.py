"""merge commitment migration heads

Revision ID: 78b62e7a6968
Revises: 0034_commitment_artifacts_table, 0035_commitment_review_items_table
Create Date: 2026-02-09 17:13:19.786163

"""

from __future__ import annotations

revision = "78b62e7a6968"
down_revision = ("0034_commitment_artifacts_table", "0035_commitment_review_items_table")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge two parallel commitment migration branches."""
    pass


def downgrade() -> None:
    """Split merge point; no schema changes are reverted."""
    pass
