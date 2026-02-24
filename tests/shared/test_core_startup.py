"""Tests for core startup ordering and migration gating behavior."""

from __future__ import annotations

from dataclasses import dataclass

from packages.brain_core.boot import BootResult
from packages.brain_core.startup import run_core_startup
from packages.brain_shared.config import BrainSettings


@dataclass(frozen=True, slots=True)
class _FakeMigrationResult:
    """Minimal migration result shape for startup orchestration tests."""

    imported_components: tuple[str, ...]
    provisioned_schemas: tuple[str, ...]
    executed_alembic_configs: tuple[str, ...]


def test_run_core_startup_runs_migrations_before_boot_hooks() -> None:
    """Startup should run migration phase before boot hook execution."""
    call_order: list[str] = []
    settings = BrainSettings()

    def _migration_runner(**_kwargs):
        call_order.append("migrate")
        return _FakeMigrationResult(
            imported_components=tuple(),
            provisioned_schemas=tuple(),
            executed_alembic_configs=tuple(),
        )

    def _hook_loader():
        call_order.append("load_hooks")
        return tuple()

    def _boot_runner(*_args, **_kwargs):
        call_order.append("boot")
        return BootResult(execution_order=tuple())

    result = run_core_startup(
        settings=settings,
        resolve_component=lambda _component_id: object(),
        migration_runner=_migration_runner,
        hook_loader=_hook_loader,
        boot_runner=_boot_runner,
    )

    assert result.migration_result is not None
    assert result.boot_result.execution_order == tuple()
    assert call_order == ["migrate", "load_hooks", "boot"]


def test_run_core_startup_skips_migrations_when_disabled() -> None:
    """Startup should skip migration phase when explicitly disabled."""
    settings = BrainSettings()
    migration_calls = {"count": 0}

    def _migration_runner(**_kwargs):
        migration_calls["count"] += 1
        return _FakeMigrationResult(
            imported_components=tuple(),
            provisioned_schemas=tuple(),
            executed_alembic_configs=tuple(),
        )

    result = run_core_startup(
        settings=settings,
        resolve_component=lambda _component_id: object(),
        run_migrations=False,
        migration_runner=_migration_runner,
        hook_loader=lambda: tuple(),
        boot_runner=lambda *_args, **_kwargs: BootResult(execution_order=tuple()),
    )

    assert migration_calls["count"] == 0
    assert result.migration_result is None
