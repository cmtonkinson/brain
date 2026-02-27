"""Core startup orchestration: migrations first, then boot hooks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from packages.brain_core.boot import (
    BootContext,
    BootResult,
    load_boot_hooks,
    run_boot_hooks,
)
from packages.brain_core.migrations import MigrationRunResult, run_startup_migrations
from packages.brain_shared.config import CoreRuntimeSettings


@dataclass(frozen=True, slots=True)
class CoreStartupResult:
    """Summary of one full core startup orchestration pass."""

    migration_result: MigrationRunResult | None
    boot_result: BootResult


def run_core_startup(
    *,
    settings: CoreRuntimeSettings,
    resolve_component: Callable[[str], object],
    run_migrations: bool | None = None,
    repo_root: Path | None = None,
    migration_runner: Callable[..., MigrationRunResult] = run_startup_migrations,
    hook_loader: Callable[[], tuple] = load_boot_hooks,
    boot_runner: Callable[..., BootResult] = run_boot_hooks,
) -> CoreStartupResult:
    """Run core startup in strict order: migrations, then boot hooks."""
    boot_settings = settings.core.boot
    execute_migrations = (
        boot_settings.run_migrations_on_startup
        if run_migrations is None
        else run_migrations
    )

    migration_result: MigrationRunResult | None = None
    if execute_migrations:
        migration_result = migration_runner(settings=settings, repo_root=repo_root)

    hooks = hook_loader()
    boot_result = boot_runner(
        hooks,
        context=BootContext(settings=settings, resolve_component=resolve_component),
        settings=boot_settings,
    )
    return CoreStartupResult(
        migration_result=migration_result,
        boot_result=boot_result,
    )
