"""create software workspaces and tasks tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from lib.shared.ids import ulid_domain_type
from services.effect.software.data.runtime import software_postgres_schema

# revision identifiers, used by Alembic.
revision = "20260502_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create Software authoritative schema objects."""
    schema = software_postgres_schema()

    op.create_table(
        "workspaces",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("default_executor", sa.String(length=32), nullable=False),
        sa.Column("test_command", sa.String(length=2048), nullable=False),
        sa.Column("max_wallclock_seconds", sa.Integer(), nullable=False),
        sa.Column("branch_prefix", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.create_index(
        "ix_workspaces_path_active",
        "workspaces",
        ["path"],
        unique=False,
        schema=schema,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "tasks",
        sa.Column("id", ulid_domain_type(schema), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            ulid_domain_type(schema),
            sa.ForeignKey(f"{schema}.workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("executor", sa.String(length=32), nullable=False),
        sa.Column("branch", sa.String(length=256), nullable=False),
        sa.Column("prompt_object_ref", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("test_passed", sa.Boolean(), nullable=True),
        sa.Column("stdout_object_ref", sa.String(length=256), nullable=True),
        sa.Column("stderr_object_ref", sa.String(length=256), nullable=True),
        sa.Column("test_stdout_object_ref", sa.String(length=256), nullable=True),
        sa.Column("test_stderr_object_ref", sa.String(length=256), nullable=True),
        sa.Column("termination_reason", sa.String(length=64), nullable=True),
        sa.Column("failure_detail", sa.String(length=4096), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adapter_handle_id", sa.String(length=128), nullable=True),
        sa.Column("adapter_container_id", sa.String(length=128), nullable=True),
        sa.Column("adapter_started_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.create_index(
        "ix_tasks_workspace_started",
        "tasks",
        ["workspace_id", "started_at"],
        unique=False,
        schema=schema,
    )


def downgrade() -> None:
    """Drop Software authoritative schema objects."""
    schema = software_postgres_schema()
    op.drop_index("ix_tasks_workspace_started", table_name="tasks", schema=schema)
    op.drop_table("tasks", schema=schema)
    op.drop_index("ix_workspaces_path_active", table_name="workspaces", schema=schema)
    op.drop_table("workspaces", schema=schema)
