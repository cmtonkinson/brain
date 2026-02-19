"""create embedding audit log table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from services.state.embedding_authority.data.runtime import embedding_postgres_schema
from services.state.embedding_authority.data.schema import EMBEDDING_AUDIT_TABLE_NAME

# revision identifiers, used by Alembic.
revision = "20260218_0001"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve the canonical EAS-owned schema name."""
    return embedding_postgres_schema()


def upgrade() -> None:
    """Create EAS-owned schema artifacts for audit logging."""
    schema = _schema()

    op.create_table(
        EMBEDDING_AUDIT_TABLE_NAME,
        sa.Column(
            "id",
            postgresql.DOMAIN(
                name="ulid_bin",
                data_type=postgresql.BYTEA(),
                schema=schema,
                create_type=False,
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("envelope_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("principal", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("namespace", sa.String(length=256), nullable=False),
        sa.Column("key", sa.String(length=512), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("outcome", sa.String(length=64), nullable=False),
        sa.Column(
            "error_code", sa.String(length=128), nullable=False, server_default=""
        ),
        schema=schema,
    )
    op.create_index(
        "ix_embedding_audit_log_occurred_at",
        EMBEDDING_AUDIT_TABLE_NAME,
        ["occurred_at"],
        unique=False,
        schema=schema,
    )
    op.create_index(
        "ix_embedding_audit_log_trace_id",
        EMBEDDING_AUDIT_TABLE_NAME,
        ["trace_id"],
        unique=False,
        schema=schema,
    )


def downgrade() -> None:
    """Drop EAS-owned audit-log artifacts."""
    schema = _schema()
    op.drop_index(
        "ix_embedding_audit_log_trace_id",
        table_name=EMBEDDING_AUDIT_TABLE_NAME,
        schema=schema,
    )
    op.drop_index(
        "ix_embedding_audit_log_occurred_at",
        table_name=EMBEDDING_AUDIT_TABLE_NAME,
        schema=schema,
    )
    op.drop_table(EMBEDDING_AUDIT_TABLE_NAME, schema=schema)
