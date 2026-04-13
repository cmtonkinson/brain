"""drop obsolete turn_summary table"""

from __future__ import annotations

from alembic import op

from services.state.memory_authority.data.runtime import memory_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260414_0006"
down_revision = "20260414_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remove obsolete per-range turn summary storage."""
    schema = memory_postgres_schema()
    op.drop_index(
        "ix_turn_summary_session_created", table_name="turn_summary", schema=schema
    )
    op.drop_table("turn_summary", schema=schema)


def downgrade() -> None:
    """Restore obsolete per-range turn summary storage."""
    schema = memory_postgres_schema()
    op.execute(
        f"""
        CREATE TABLE {schema}.turn_summary (
            id {schema}.ulid_bin PRIMARY KEY NOT NULL,
            session_id {schema}.ulid_bin NOT NULL REFERENCES {schema}.session(id) ON DELETE RESTRICT,
            start_turn_id {schema}.ulid_bin NOT NULL REFERENCES {schema}.turn(id) ON DELETE RESTRICT,
            end_turn_id {schema}.ulid_bin NOT NULL REFERENCES {schema}.turn(id) ON DELETE RESTRICT,
            content TEXT NOT NULL,
            token_count INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_turn_summary_session_range UNIQUE (session_id, start_turn_id, end_turn_id),
            CONSTRAINT ck_turn_summary_token_count_nonnegative CHECK (token_count >= 0)
        )
        """
    )
    op.create_index(
        "ix_turn_summary_session_created",
        "turn_summary",
        ["session_id", "created_at"],
        unique=False,
        schema=schema,
    )
