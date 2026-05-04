"""Table models for Software Service workspace allowlist + task lineage.

Two tables in the ``service_software`` schema:

- ``workspaces`` — operator-allowlisted repository roots. ``revoked_at`` is
  set on revocation; rows are not deleted so the audit history is durable.
- ``tasks`` — one row per dispatched coding task, capturing the full
  lifecycle (status, branch, commit, test outcome, log refs).
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    func,
)

from lib.shared.ids import ulid_domain_type, ulid_primary_key_column
from services.effect.software.data.runtime import software_postgres_schema

metadata = MetaData()


workspaces = Table(
    "workspaces",
    metadata,
    ulid_primary_key_column("id", schema_name=software_postgres_schema()),
    Column("path", String(1024), nullable=False),
    Column("default_executor", String(32), nullable=False),
    Column("test_command", String(2048), nullable=False),
    Column("max_wallclock_seconds", Integer, nullable=False),
    Column("branch_prefix", String(128), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
)


tasks = Table(
    "tasks",
    metadata,
    ulid_primary_key_column("id", schema_name=software_postgres_schema()),
    Column(
        "workspace_id",
        ulid_domain_type(software_postgres_schema()),
        ForeignKey(f"{software_postgres_schema()}.workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("executor", String(32), nullable=False),
    Column("branch", String(256), nullable=False),
    Column("prompt_object_ref", String(256), nullable=True),
    Column("status", String(32), nullable=False),
    Column("commit_sha", String(64), nullable=True),
    Column("test_passed", Boolean, nullable=True),
    Column("stdout_object_ref", String(256), nullable=True),
    Column("stderr_object_ref", String(256), nullable=True),
    Column("test_stdout_object_ref", String(256), nullable=True),
    Column("test_stderr_object_ref", String(256), nullable=True),
    Column("termination_reason", String(64), nullable=True),
    Column("failure_detail", String(4096), nullable=True),
    Column(
        "started_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("adapter_handle_id", String(128), nullable=True),
    Column("adapter_container_id", String(128), nullable=True),
    Column("adapter_started_at", DateTime(timezone=True), nullable=True),
)
