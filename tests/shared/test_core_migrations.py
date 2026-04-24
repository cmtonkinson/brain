"""Tests for core startup migration discovery and execution behavior."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from lib.core.migrations import (
    MigrationExecutionError,
    discover_service_migration_configs,
    run_startup_migrations,
)
from lib.shared.config import (
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)


@dataclass(frozen=True, slots=True)
class _FakeService:
    """Minimal service manifest shape for migration discovery tests."""

    plane: str
    module_roots: frozenset[str]


_PLANE_SORT_KEY: dict[str, int] = {"state": 0, "effect": 1, "reason": 2}


@dataclass(frozen=True, slots=True)
class _FakeRegistry:
    """Minimal registry shape for migration discovery tests.

    list_services() returns services sorted by plane (state, effect, reason),
    matching the real registry contract that discover_service_migration_configs
    relies on for migration execution order.
    """

    services: tuple[_FakeService, ...]

    def assert_valid(self) -> None:
        """Satisfy registry contract used by migration discovery."""

    def list_services(self) -> tuple[_FakeService, ...]:
        """Return services sorted by plane, mirroring the real registry."""
        return tuple(sorted(self.services, key=lambda s: _PLANE_SORT_KEY[s.plane]))


def test_discover_service_migration_configs_orders_by_plane(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Discovery should emit registered service alembic configs in registry plane order."""
    state_ini = tmp_path / "services" / "state" / "a" / "migrations" / "alembic.ini"
    reason_ini = tmp_path / "services" / "reason" / "b" / "migrations" / "alembic.ini"
    state_ini.parent.mkdir(parents=True)
    reason_ini.parent.mkdir(parents=True)
    state_ini.write_text("[alembic]\n", encoding="utf-8")
    reason_ini.write_text("[alembic]\n", encoding="utf-8")

    registry = _FakeRegistry(
        services=(
            _FakeService(plane="reason", module_roots=frozenset({"services.reason.b"})),
            _FakeService(plane="state", module_roots=frozenset({"services.state.a"})),
            _FakeService(plane="effect", module_roots=frozenset({"services.effect.c"})),
        )
    )
    monkeypatch.setattr(
        "lib.core.migrations.import_registered_component_modules",
        lambda: tuple(),
    )
    monkeypatch.setattr("lib.core.migrations.get_registry", lambda: registry)

    configs = discover_service_migration_configs(repo_root=tmp_path)

    assert configs == (state_ini, reason_ini)


def test_run_startup_migrations_executes_bootstrap_then_alembic_upgrades(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Migration runner should include bootstrap result and execute each config."""
    ini_a = tmp_path / "services" / "state" / "a" / "migrations" / "alembic.ini"
    ini_b = tmp_path / "services" / "effect" / "b" / "migrations" / "alembic.ini"
    ini_a.parent.mkdir(parents=True)
    ini_b.parent.mkdir(parents=True)
    ini_a.write_text("[alembic]\n", encoding="utf-8")
    ini_b.write_text("[alembic]\n", encoding="utf-8")

    monkeypatch.setattr(
        "lib.core.migrations.bootstrap_service_schemas",
        lambda settings: SimpleNamespace(
            imported_components=("services.state.a.component",),
            provisioned_schemas=("service_a",),
        ),
    )
    monkeypatch.setattr(
        "lib.core.migrations.discover_service_migration_configs",
        lambda repo_root=None: (ini_a, ini_b),
    )

    calls: list[tuple[str, str]] = []

    def _upgrade(config: Config, revision: str) -> None:
        calls.append((str(config.config_file_name), revision))

    result = run_startup_migrations(
        settings=CoreRuntimeSettings(
            core=CoreSettings(), resources=ResourcesSettings()
        ),
        repo_root=tmp_path,
        upgrade_fn=_upgrade,
    )

    assert result.imported_components == ("services.state.a.component",)
    assert result.provisioned_schemas == ("service_a",)
    assert result.executed_alembic_configs == (str(ini_a), str(ini_b))
    assert calls == [(str(ini_a), "head"), (str(ini_b), "head")]


def test_run_startup_migrations_raises_on_upgrade_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Migration runner should fail hard when one alembic upgrade errors."""
    ini = tmp_path / "services" / "state" / "a" / "migrations" / "alembic.ini"
    ini.parent.mkdir(parents=True)
    ini.write_text("[alembic]\n", encoding="utf-8")

    monkeypatch.setattr(
        "lib.core.migrations.bootstrap_service_schemas",
        lambda settings: SimpleNamespace(
            imported_components=tuple(),
            provisioned_schemas=tuple(),
        ),
    )
    monkeypatch.setattr(
        "lib.core.migrations.discover_service_migration_configs",
        lambda repo_root=None: (ini,),
    )

    with pytest.raises(MigrationExecutionError):
        run_startup_migrations(
            settings=CoreRuntimeSettings(
                core=CoreSettings(), resources=ResourcesSettings()
            ),
            repo_root=tmp_path,
            upgrade_fn=lambda config, revision: (_ for _ in ()).throw(
                RuntimeError("boom")
            ),
        )


def test_all_checked_in_alembic_configs_resolve_real_script_directories() -> None:
    """Every real service alembic.ini should resolve to a valid migration environment."""
    repo_root = Path(__file__).resolve().parents[2]

    configs = discover_service_migration_configs(repo_root=repo_root)

    assert configs, "expected at least one registered service migration config"
    for config_path in configs:
        assert config_path.exists()
        assert config_path.parent.joinpath("env.py").exists()
        script = ScriptDirectory.from_config(Config(str(config_path)))
        assert Path(script.dir).resolve() == config_path.parent.resolve()
