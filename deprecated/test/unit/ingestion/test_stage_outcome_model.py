"""Tests for ingestion stage outcome model and migration."""

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
    """Load the ingestion stage runs migration module from disk."""
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0028_ingestion_stage_runs_table.py"
    )
    spec = importlib.util.spec_from_file_location("ingestion_stage_runs_table", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load ingestion stage runs migration module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ingestion_stage_runs_migration_upgrade_generates_sql() -> None:
    """Ensure upgrade emits ingestion_stage_runs table creation SQL."""
    migration = _load_migration_module()

    sql = _run_migration(migration, migration.upgrade)

    assert "CREATE TABLE ingestion_stage_runs" in sql
    assert "ck_ingestion_stage_runs_stage" in sql
    assert "ck_ingestion_stage_runs_status" in sql
    assert "stage IN ('store', 'extract', 'normalize', 'anchor')" in sql
    assert "status IN ('success', 'failed', 'skipped')" in sql
    assert "ingestion_id" in sql
    assert "started_at" in sql
    assert "finished_at" in sql
    assert "error" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql


def test_ingestion_stage_runs_migration_downgrade_generates_sql() -> None:
    """Ensure downgrade emits ingestion_stage_runs table drop SQL."""
    migration = _load_migration_module()

    sql = _run_migration(migration, migration.downgrade)

    assert "DROP TABLE ingestion_stage_runs" in sql
