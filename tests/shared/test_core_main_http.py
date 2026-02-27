"""Tests for core HTTP runtime registration behavior."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from unittest.mock import MagicMock, patch


from packages.brain_core.main import _start_http_runtime
from packages.brain_shared.config import (
    CoreHttpSettings,
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)


@dataclass(frozen=True, slots=True)
class _Manifest:
    """Minimal service manifest shape for tests."""

    id: str

    @property
    def module_roots(self) -> frozenset[str]:
        return frozenset()


class _Registry:
    def __init__(self, services: tuple[_Manifest, ...]) -> None:
        self._services = services

    def list_services(self) -> tuple[_Manifest, ...]:
        return self._services


def test_start_http_runtime_registers_routes_and_starts() -> None:
    """HTTP runtime should register available routes and start server thread."""
    settings = CoreRuntimeSettings(
        core=CoreSettings(http=CoreHttpSettings(socket_path="/tmp/test-brain.sock")),
        resources=ResourcesSettings(),
    )
    registry = _Registry(
        services=(_Manifest(id="service_a"), _Manifest(id="service_b"))
    )
    components = {"service_a": object(), "service_b": object()}
    registered: list[str] = []

    fake_server = MagicMock()
    fake_server.run = lambda: None  # called in daemon thread

    def _resolver(manifest: _Manifest):
        if manifest.id == "service_a":
            return lambda *, router, service: registered.append("service_a")
        return None

    with (
        patch("packages.brain_core.main.get_registry", return_value=registry),
        patch(
            "packages.brain_core.main._resolve_service_http_registrar",
            side_effect=_resolver,
        ),
        patch("packages.brain_core.main.run_app_uds", return_value=fake_server),
        patch("packages.brain_core.main.create_app") as mock_create_app,
        patch("packages.brain_core.main.register_routes"),
    ):
        mock_app = MagicMock()
        mock_create_app.return_value = mock_app

        server, thread = _start_http_runtime(settings=settings, components=components)

    assert server is fake_server
    assert registered == ["service_a"]
    assert isinstance(thread, threading.Thread)
