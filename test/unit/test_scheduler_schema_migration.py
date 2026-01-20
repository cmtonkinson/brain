"""Tests for scheduler schema migration SQL generation."""

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
    """Load the scheduler migration module from disk."""
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0016_scheduler_schema_migrations.py"
    )
    spec = importlib.util.spec_from_file_location("scheduler_schema_migrations", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load scheduler migration module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scheduler_migration_upgrade_generates_sql() -> None:
    """Ensure upgrade emits expected scheduler tables and constraints."""
    migration = _load_migration_module()

    sql = _run_migration(migration, migration.upgrade)

    assert "CREATE TABLE task_intents" in sql
    assert "CREATE TABLE schedules" in sql
    assert "CREATE TABLE executions" in sql
    assert "ck_schedules_conditional_eval_cadence" in sql


def test_scheduler_migration_downgrade_generates_sql() -> None:
    """Ensure downgrade emits drop statements for scheduler tables."""
    migration = _load_migration_module()

    sql = _run_migration(migration, migration.downgrade)

    assert "DROP TABLE executions" in sql
    assert "DROP TABLE schedules" in sql
    assert "DROP TABLE task_intents" in sql
