"""Tests for optional core boot hook discovery and contract loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from types import ModuleType

import pytest

from packages.brain_core.boot import BootContext
from packages.brain_shared.config import (
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)

from packages.brain_core.boot.contracts import BootContractError
from packages.brain_core.boot.loader import (
    BootModuleSpec,
    discover_boot_modules,
    load_boot_hooks,
)


@dataclass(frozen=True, slots=True)
class _FakeComponent:
    """Minimal component model for boot loader unit tests."""

    id: str
    module_roots: frozenset[str]


def test_discover_boot_modules_only_includes_present_specs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery should only emit module roots that expose ``<root>.boot``."""

    monkeypatch.setattr(
        "packages.brain_core.boot.loader.import_registered_component_modules",
        lambda: tuple(),
    )
    monkeypatch.setattr(
        "packages.brain_core.boot.loader.list_components",
        lambda: (
            _FakeComponent(id="service_a", module_roots=frozenset({"services.a"})),
            _FakeComponent(id="service_b", module_roots=frozenset({"services.b"})),
        ),
    )
    monkeypatch.setattr(
        "packages.brain_core.boot.loader.Path.cwd",
        lambda: Path("/repo"),
    )
    monkeypatch.setattr(
        "packages.brain_core.boot.loader.Path.exists",
        lambda self: str(self).endswith("services/a/boot.py"),
    )

    discovered = discover_boot_modules()

    assert discovered == (
        BootModuleSpec(component_id="service_a", module_name="services.a.boot"),
    )


def test_load_boot_hooks_rejects_invalid_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contract loading should fail when required attributes are malformed."""

    module = ModuleType("services.a.boot")
    module.dependencies = "service_b"
    module.is_ready = lambda _ctx: True
    module.boot = lambda _ctx: None

    monkeypatch.setattr(
        "packages.brain_core.boot.loader.discover_boot_modules",
        lambda: (
            BootModuleSpec(component_id="service_a", module_name="services.a.boot"),
        ),
    )
    monkeypatch.setattr(
        "packages.brain_core.boot.loader.import_component_modules",
        lambda _: tuple(),
    )
    monkeypatch.setitem(sys.modules, "services.a.boot", module)

    with pytest.raises(BootContractError):
        load_boot_hooks()


def test_load_boot_hooks_loads_valid_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract loading should normalize dependencies and expose callables."""

    module = ModuleType("services.a.boot")
    module.dependencies = ["service_b", "service_b", "service_c"]
    module.is_ready = lambda _ctx: True
    module.boot = lambda _ctx: None

    monkeypatch.setattr(
        "packages.brain_core.boot.loader.discover_boot_modules",
        lambda: (
            BootModuleSpec(component_id="service_a", module_name="services.a.boot"),
        ),
    )
    monkeypatch.setattr(
        "packages.brain_core.boot.loader.import_component_modules",
        lambda _: tuple(),
    )
    monkeypatch.setitem(sys.modules, "services.a.boot", module)

    hooks = load_boot_hooks()

    assert len(hooks) == 1
    assert hooks[0].component_id == "service_a"
    assert hooks[0].dependencies == ("service_b", "service_c")
    context = BootContext(
        settings=CoreRuntimeSettings(
            core=CoreSettings(), resources=ResourcesSettings()
        ),
        resolve_component=lambda _component_id: object(),
    )
    assert hooks[0].is_ready(context) is True
