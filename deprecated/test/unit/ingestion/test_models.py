"""Tests for ingestion schema migrations."""

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
    """Load the ingestion migration module from disk."""
    migration_path = (
        Path(__file__).resolve().parents[3] / "alembic" / "versions" / "0021_ingestions_table.py"
    )
    spec = importlib.util.spec_from_file_location("ingestions_table", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load ingestion migration module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ingestions_migration_upgrade_generates_sql() -> None:
    """Ensure upgrade emits ingestion table creation SQL."""
    migration = _load_migration_module()

    sql = _run_migration(migration, migration.upgrade)

    assert "CREATE TABLE ingestions" in sql
    assert "ck_ingestions_status" in sql
    assert "status IN ('queued', 'running', 'complete', 'failed')" in sql
    assert "queued" in sql
    assert "UUID" in sql


def test_ingestions_migration_downgrade_generates_sql() -> None:
    """Ensure downgrade emits ingestion table drop SQL."""
    migration = _load_migration_module()

    sql = _run_migration(migration, migration.downgrade)

    assert "DROP TABLE ingestions" in sql
