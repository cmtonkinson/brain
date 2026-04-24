"""add dynamic op classifications table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from lib.shared.ids import ulid_domain_type
from services.effect.execution.data.runtime import execution_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260428_0003"
down_revision = "20260307_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create Execution-owned dynamic op classification table."""
    schema = execution_postgres_schema()
    op.create_table(
        "dynamic_op_classifications",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("op_id", sa.String(length=128), nullable=False),
        sa.Column("source_kind", sa.String(length=64), nullable=False),
        sa.Column("source_ref", sa.String(length=256), nullable=False),
        sa.Column("definition_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "summary",
            sa.String(length=2048),
            nullable=False,
            server_default="",
        ),
        sa.Column("input_schema_json", sa.Text(), nullable=True),
        sa.Column("output_schema_json", sa.Text(), nullable=True),
        sa.Column("effect", sa.String(length=32), nullable=True),
        sa.Column("approval", sa.String(length=32), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("op_id", name="uq_dynamic_op_classifications_op_id"),
        schema=schema,
    )


def downgrade() -> None:
    """Drop Execution-owned dynamic op classification table."""
    op.drop_table(
        "dynamic_op_classifications",
        schema=execution_postgres_schema(),
    )
