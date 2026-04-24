"""nullable finish_reason and error_message on call_audits"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from services.effect.language.data.runtime import language_model_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260426_0003"
down_revision = "20260417_0002"
branch_labels = None
depends_on = None


def _schema() -> str:
    return language_model_postgres_schema()


def upgrade() -> None:
    schema = _schema()
    op.alter_column(
        "call_audits",
        "finish_reason",
        nullable=True,
        server_default=None,
        schema=schema,
    )
    op.alter_column(
        "call_audits",
        "error_message",
        nullable=True,
        server_default=None,
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()
    op.execute(
        sa.text(
            f"UPDATE {schema}.call_audits SET finish_reason = '' WHERE finish_reason IS NULL"
        )
    )
    op.execute(
        sa.text(
            f"UPDATE {schema}.call_audits SET error_message = '' WHERE error_message IS NULL"
        )
    )
    op.alter_column(
        "call_audits", "finish_reason", nullable=False, server_default="", schema=schema
    )
    op.alter_column(
        "call_audits", "error_message", nullable=False, server_default="", schema=schema
    )
