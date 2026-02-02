"""Schema tests for the extraction metadata migration."""

import importlib.util
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations


def _run_migration(module: object, fn: callable) -> str:
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
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0024_extraction_metadata_table.py"
    )
    spec = importlib.util.spec_from_file_location("extraction_metadata_table", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load extraction metadata migration module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extraction_metadata_migration_upgrade_generates_sql() -> None:
    """Ensure the extraction metadata migration emits the correct SQL."""
    migration = _load_migration_module()
    sql = _run_migration(migration, migration.upgrade)
    assert "CREATE TABLE extraction_metadata" in sql
    assert "tool_metadata" in sql
    assert "JSONB" in sql


def test_extraction_metadata_migration_downgrade_generates_sql() -> None:
    """Ensure the extraction metadata migration drop SQL can be generated."""
    migration = _load_migration_module()
    sql = _run_migration(migration, migration.downgrade)
    assert "DROP TABLE extraction_metadata" in sql
