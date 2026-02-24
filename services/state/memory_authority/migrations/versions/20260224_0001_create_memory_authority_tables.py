"""create memory authority tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from packages.brain_shared.ids.constants import ULID_DOMAIN_NAME
from services.state.memory_authority.data.runtime import memory_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260224_0001"
down_revision = None
branch_labels = None
depends_on = None


def _schema() -> str:
    """Resolve canonical MAS-owned schema name."""
    return memory_postgres_schema()


def _ulid_domain(schema: str) -> postgresql.DOMAIN:
    """Return schema-local ``ulid_bin`` domain reference."""
    return postgresql.DOMAIN(
        name=ULID_DOMAIN_NAME,
        data_type=postgresql.BYTEA(),
        schema=schema,
        create_type=False,
    )


def _direction_enum(schema: str, *, create_type: bool = False) -> postgresql.ENUM:
    """Return schema-local ``turn_direction`` enum reference."""
    return postgresql.ENUM(
        "inbound",
        "outbound",
        name="turn_direction",
        schema=schema,
        create_type=create_type,
    )


def upgrade() -> None:
    """Create MAS authoritative schema objects."""
    schema = _schema()
    _direction_enum(schema, create_type=True).create(op.get_bind(), checkfirst=True)

    op.create_table(
        "session",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("focus", sa.Text(), nullable=True),
        sa.Column("focus_token_count", sa.Integer(), nullable=True),
        sa.Column("dialogue_start_turn_id", _ulid_domain(schema), nullable=True),
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
        sa.CheckConstraint(
            "focus_token_count IS NULL OR focus_token_count >= 0",
            name="ck_session_focus_token_count_nonnegative",
        ),
        schema=schema,
    )

    op.create_table(
        "turn",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("session_id", _ulid_domain(schema), nullable=False),
        sa.Column("direction", _direction_enum(schema), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=True),
        sa.Column("provider", sa.String(length=128), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("reasoning_level", sa.String(length=64), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("principal", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], [f"{schema}.session.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "token_count IS NULL OR token_count >= 0",
            name="ck_turn_token_count_nonnegative",
        ),
        schema=schema,
    )

    op.create_table(
        "turn_summary",
        sa.Column("id", _ulid_domain(schema), primary_key=True, nullable=False),
        sa.Column("session_id", _ulid_domain(schema), nullable=False),
        sa.Column("start_turn_id", _ulid_domain(schema), nullable=False),
        sa.Column("end_turn_id", _ulid_domain(schema), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], [f"{schema}.session.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["start_turn_id"], [f"{schema}.turn.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["end_turn_id"], [f"{schema}.turn.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "session_id",
            "start_turn_id",
            "end_turn_id",
            name="uq_turn_summary_session_range",
        ),
        sa.CheckConstraint(
            "token_count >= 0",
            name="ck_turn_summary_token_count_nonnegative",
        ),
        schema=schema,
    )

    op.create_foreign_key(
        "fk_session_dialogue_start_turn",
        source_table="session",
        referent_table="turn",
        local_cols=["dialogue_start_turn_id"],
        remote_cols=["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_turn_session_created",
        "turn",
        ["session_id", "created_at"],
        unique=False,
        schema=schema,
    )
    op.create_index(
        "ix_turn_summary_session_created",
        "turn_summary",
        ["session_id", "created_at"],
        unique=False,
        schema=schema,
    )


def downgrade() -> None:
    """Drop MAS authoritative schema objects."""
    schema = _schema()

    op.drop_index(
        "ix_turn_summary_session_created", table_name="turn_summary", schema=schema
    )
    op.drop_index("ix_turn_session_created", table_name="turn", schema=schema)

    op.drop_constraint(
        "fk_session_dialogue_start_turn",
        table_name="session",
        schema=schema,
        type_="foreignkey",
    )

    op.drop_table("turn_summary", schema=schema)
    op.drop_table("turn", schema=schema)
    op.drop_table("session", schema=schema)

    direction_enum = _direction_enum(schema, create_type=True)
    direction_enum.drop(op.get_bind(), checkfirst=True)
