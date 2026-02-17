"""Tests for predicate evaluation audit schema migration SQL generation."""

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
    """Load the predicate evaluation audit migration module from disk."""
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0018_predicate_evaluation_audit_schema.py"
    )
    spec = importlib.util.spec_from_file_location(
        "predicate_evaluation_audit_schema",
        migration_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load predicate evaluation audit migration module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_predicate_evaluation_audit_migration_upgrade_generates_sql() -> None:
    """Ensure upgrade emits expected predicate evaluation audit table and indexes."""
    migration = _load_migration_module()

    sql = _run_migration(migration, migration.upgrade)

    assert "CREATE TABLE predicate_evaluation_audit_logs" in sql
    assert "ix_predicate_eval_audit_schedule_id" in sql
    assert "ix_predicate_eval_audit_execution_id" in sql
    assert "ix_predicate_eval_audit_evaluated_at" in sql


def test_predicate_evaluation_audit_migration_downgrade_generates_sql() -> None:
    """Ensure downgrade emits drop statements for predicate evaluation audit table."""
    migration = _load_migration_module()

    sql = _run_migration(migration, migration.downgrade)

    assert "DROP TABLE predicate_evaluation_audit_logs" in sql
