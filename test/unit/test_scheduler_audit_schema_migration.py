"""Tests for scheduler audit schema migration SQL generation."""

from __future__ import annotations

import io
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations


def _run_migration(module: object, fn: callable) -> str:
    """Run a migration function against a PostgreSQL SQL buffer."""
    buffer = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": buffer},
    )
    operations = Operations(context)
    previous_op = getattr(module, "op")
    setattr(module, "op", operations)
    try:
        fn()
    finally:
        setattr(module, "op", previous_op)
    return buffer.getvalue()


def _load_migration_module() -> object:
    """Load the scheduler audit migration module from disk."""
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0017_scheduler_audit_schema.py"
    )
    spec = importlib.util.spec_from_file_location("scheduler_audit_schema", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load scheduler audit migration module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scheduler_audit_migration_upgrade_generates_sql() -> None:
    """Ensure upgrade emits expected scheduler audit tables and indexes."""
    migration = _load_migration_module()

    sql = _run_migration(migration, migration.upgrade)

    assert "CREATE TABLE schedule_audit_logs" in sql
    assert "CREATE TABLE execution_audit_logs" in sql
    assert "ix_schedule_audit_logs_schedule_id" in sql
    assert "ix_execution_audit_logs_execution_id" in sql


def test_scheduler_audit_migration_downgrade_generates_sql() -> None:
    """Ensure downgrade emits drop statements for scheduler audit tables."""
    migration = _load_migration_module()

    sql = _run_migration(migration, migration.downgrade)

    assert "DROP TABLE execution_audit_logs" in sql
    assert "DROP TABLE schedule_audit_logs" in sql
