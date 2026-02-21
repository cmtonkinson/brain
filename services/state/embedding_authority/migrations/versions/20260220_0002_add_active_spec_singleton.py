"""add active spec singleton table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from packages.brain_shared.ids.constants import ULID_DOMAIN_NAME
from services.state.embedding_authority.data.runtime import embedding_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260220_0002"
down_revision = "20260218_0001"
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve the canonical EAS-owned schema name."""
    return embedding_postgres_schema()


def _ulid_domain(schema: str) -> postgresql.DOMAIN:
    """Return schema-local ``ulid_bin`` domain reference."""
    return postgresql.DOMAIN(
        name=ULID_DOMAIN_NAME,
        data_type=postgresql.BYTEA(),
        schema=schema,
        create_type=False,
    )


def upgrade() -> None:
    """Create active-spec singleton state table."""
    schema = _schema()

    op.create_table(
        "active_spec",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("singleton_marker", sa.String(length=16), nullable=False),
        sa.Column("spec_id", _ulid_domain(schema), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["spec_id"], [f"{schema}.specs.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "singleton_marker",
            name="uq_active_spec_singleton_marker",
        ),
        sa.CheckConstraint(
            "singleton_marker = 'active'",
            name="ck_active_spec_singleton_marker",
        ),
        schema=schema,
    )


def downgrade() -> None:
    """Drop active-spec singleton state table."""
    schema = _schema()
    op.drop_table("active_spec", schema=schema)
