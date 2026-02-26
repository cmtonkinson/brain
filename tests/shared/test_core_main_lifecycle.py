"""Tests for optional post-boot component lifecycle execution in core main."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from packages.brain_core.main import _run_after_boot_lifecycle
from packages.brain_shared.config import BrainSettings


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


def test_run_after_boot_lifecycle_calls_hooks_in_component_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle runner should invoke optional hooks in instantiated component order."""
    calls: list[str] = []
    registry = _Registry(
        services=(_Manifest(id="service_a"), _Manifest(id="service_b")),
    )
    components = {"service_a": object(), "service_b": object()}

    monkeypatch.setattr("packages.brain_core.main.get_registry", lambda: registry)

    def _resolver(manifest: _Manifest):
        if manifest.id == "service_a":
            return lambda **_kwargs: calls.append("service_a")
        if manifest.id == "service_b":
            return lambda **_kwargs: calls.append("service_b")
        return None

    monkeypatch.setattr(
        "packages.brain_core.main._resolve_component_after_boot", _resolver
    )

    _run_after_boot_lifecycle(settings=BrainSettings(), components=components)

    assert calls == ["service_a", "service_b"]


def test_run_after_boot_lifecycle_raises_for_unknown_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle runner should fail hard when a built component lacks a manifest."""
    registry = _Registry(services=(_Manifest(id="service_a"),))
    monkeypatch.setattr("packages.brain_core.main.get_registry", lambda: registry)

    with pytest.raises(RuntimeError, match="missing from registry"):
        _run_after_boot_lifecycle(
            settings=BrainSettings(),
            components={"service_missing": object()},
        )
