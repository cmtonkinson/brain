"""create language model call audit table"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from lib.shared.ids import ulid_domain_type
from services.effect.language.data.runtime import language_model_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260307_0001"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical Language-owned schema name."""
    return language_model_postgres_schema()


def upgrade() -> None:
    """Create Language authoritative schema objects."""
    schema = _schema()

    op.create_table(
        "call_audits",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("envelope_id", sa.String(length=26), nullable=False),
        sa.Column("trace_id", sa.String(length=26), nullable=False),
        sa.Column("parent_id", sa.String(length=26), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("principal", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("profile", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("request_phase", sa.String(length=32), nullable=False),
        sa.Column("outcome_kind", sa.String(length=32), nullable=False),
        sa.Column("call_index", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column(
            "finish_reason", sa.String(length=64), nullable=False, server_default=""
        ),
        sa.Column(
            "error_message", sa.String(length=4096), nullable=False, server_default=""
        ),
        sa.Column(
            "request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=schema,
    )
    op.create_index(
        "ix_call_audits_trace_index",
        "call_audits",
        ["trace_id", "call_index"],
        unique=False,
        schema=schema,
    )


def downgrade() -> None:
    """Drop Language authoritative schema objects."""
    schema = _schema()
    op.drop_index("ix_call_audits_trace_index", table_name="call_audits", schema=schema)
    op.drop_table("call_audits", schema=schema)
