"""Tests for optional post-boot component lifecycle execution in core main."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from lib.core.main import _assert_health_interface, _run_after_boot_lifecycle
from lib.shared.config import (
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)


@dataclass(frozen=True, slots=True)
class _Manifest:
    """Minimal manifest shape required by ``_run_after_boot_lifecycle``."""

    id: str


class _Registry:
    """Minimal registry shape required by ``_run_after_boot_lifecycle``."""

    def __init__(
        self,
        *,
        resources: tuple[_Manifest, ...] = tuple(),
        services: tuple[_Manifest, ...] = tuple(),
    ) -> None:
        self._resources = resources
        self._services = services

    def list_resources(self) -> tuple[_Manifest, ...]:
        """Return configured resource manifests."""
        return self._resources

    def list_services(self) -> tuple[_Manifest, ...]:
        """Return configured service manifests."""
        return self._services


def test_assert_health_interface_passes_when_all_have_health() -> None:
    """Validation should succeed when every component exposes health()."""

    class _Ok:
        def health(self) -> None:
            pass

    _assert_health_interface({"service_a": _Ok(), "resource_b": _Ok()})


def test_assert_health_interface_raises_for_missing_health() -> None:
    """Validation should raise immediately when any component lacks health()."""

    class _Ok:
        def health(self) -> None:
            pass

    class _Bad:
        pass

    with pytest.raises(RuntimeError, match="service_bad"):
        _assert_health_interface({"service_good": _Ok(), "service_bad": _Bad()})


def test_assert_health_interface_raises_for_non_callable_health() -> None:
    """health attribute must be callable, not just present."""

    class _Bad:
        health = "not-callable"

    with pytest.raises(RuntimeError, match="service_bad"):
        _assert_health_interface({"service_bad": _Bad()})


def test_run_after_boot_lifecycle_calls_hooks_in_component_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle runner should invoke optional hooks in instantiated component order."""
    calls: list[str] = []
    registry = _Registry(
        services=(_Manifest(id="service_a"), _Manifest(id="service_b")),
    )
    components = {"service_a": object(), "service_b": object()}

    monkeypatch.setattr("lib.core.main.get_registry", lambda: registry)

    def _resolver(manifest: _Manifest):
        if manifest.id == "service_a":
            return lambda **_kwargs: calls.append("service_a")
        if manifest.id == "service_b":
            return lambda **_kwargs: calls.append("service_b")
        return None

    monkeypatch.setattr("lib.core.main._resolve_component_after_boot", _resolver)

    _run_after_boot_lifecycle(
        settings=CoreRuntimeSettings(
            core=CoreSettings(), resources=ResourcesSettings()
        ),
        components=components,
    )

    assert calls == ["service_a", "service_b"]


def test_run_after_boot_lifecycle_raises_for_unknown_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle runner should fail hard when a built component lacks a manifest."""
    registry = _Registry(services=(_Manifest(id="service_a"),))
    monkeypatch.setattr("lib.core.main.get_registry", lambda: registry)

    with pytest.raises(RuntimeError, match="missing from registry"):
        _run_after_boot_lifecycle(
            settings=CoreRuntimeSettings(
                core=CoreSettings(), resources=ResourcesSettings()
            ),
            components={"service_missing": object()},
        )
