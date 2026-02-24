"""Core-managed startup migration orchestration for registered services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config

from packages.brain_shared.component_loader import import_registered_component_modules
from packages.brain_shared.config import BrainSettings
from packages.brain_shared.manifest import get_registry
from resources.substrates.postgres.bootstrap import bootstrap_service_schemas

_SYSTEM_ORDER: tuple[str, ...] = ("state", "action", "control")


class MigrationExecutionError(RuntimeError):
    """Raised when startup migration execution fails."""


@dataclass(frozen=True, slots=True)
class MigrationRunResult:
    """Summary of one startup migration pass."""

    imported_components: tuple[str, ...]
    provisioned_schemas: tuple[str, ...]
    executed_alembic_configs: tuple[str, ...]


def discover_service_migration_configs(
    *,
    repo_root: Path | None = None,
) -> tuple[Path, ...]:
    """Discover alembic config files for registered services in system order."""
    root = (repo_root or Path.cwd()).resolve()
    import_registered_component_modules()
    registry = get_registry()
    registry.assert_valid()
    services = registry.list_services()

    config_paths: list[Path] = []
    for system in _SYSTEM_ORDER:
        for service in services:
            if service.system != system:
                continue
            for module_root in sorted(service.module_roots):
                candidate = (
                    root
                    / Path(*str(module_root).split("."))
                    / "migrations"
                    / "alembic.ini"
                )
                if candidate.exists():
                    config_paths.append(candidate)
                    break
    return tuple(config_paths)


def run_startup_migrations(
    *,
    settings: BrainSettings,
    repo_root: Path | None = None,
    upgrade_fn: Callable[[Config, str], None] = command.upgrade,
) -> MigrationRunResult:
    """Bootstrap schemas and run Alembic upgrades for registered services."""
    bootstrap_result = bootstrap_service_schemas(settings=settings)
    configs = discover_service_migration_configs(repo_root=repo_root)

    executed: list[str] = []
    for config_path in configs:
        try:
            upgrade_fn(Config(str(config_path)), "head")
        except Exception as exc:
            raise MigrationExecutionError(
                f"startup migration failed for config '{config_path}'"
            ) from exc
        executed.append(str(config_path))

    return MigrationRunResult(
        imported_components=bootstrap_result.imported_components,
        provisioned_schemas=bootstrap_result.provisioned_schemas,
        executed_alembic_configs=tuple(executed),
    )
