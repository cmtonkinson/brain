"""Negative fixture: migration violating PK and FK schema invariants."""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    """Create an invalid table."""
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("other_id", sa.String(length=26), nullable=False),
        sa.ForeignKeyConstraint(["other_id"], ["other_schema.items.id"]),
        schema="service_example",
    )
