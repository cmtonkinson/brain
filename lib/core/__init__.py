"""Public API for Brain core startup and boot orchestration."""

from lib.core.boot import (
    BootContext,
    BootContractError,
    BootDependencyError,
    BootError,
    BootHookContract,
    BootHookExecutionError,
    BootModuleSpec,
    BootReadinessTimeoutError,
    BootResult,
    discover_boot_modules,
    load_boot_hooks,
    run_boot_hooks,
)
from lib.core.health import ComponentHealthResult, CoreHealthResult
from lib.core.migrations import (
    MigrationExecutionError,
    MigrationRunResult,
    discover_service_migration_configs,
    run_startup_migrations,
)
from lib.core.startup import CoreStartupResult, run_core_startup

__all__ = [
    "BootContext",
    "BootContractError",
    "BootDependencyError",
    "BootError",
    "BootHookContract",
    "BootHookExecutionError",
    "BootModuleSpec",
    "BootReadinessTimeoutError",
    "BootResult",
    "ComponentHealthResult",
    "CoreHealthResult",
    "CoreStartupResult",
    "MigrationExecutionError",
    "MigrationRunResult",
    "discover_boot_modules",
    "discover_service_migration_configs",
    "load_boot_hooks",
    "run_boot_hooks",
    "run_core_startup",
    "run_startup_migrations",
]
