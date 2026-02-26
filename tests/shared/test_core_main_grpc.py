"""Tests for core gRPC runtime registration and bind behavior."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from packages.brain_core.main import _start_grpc_runtime
from packages.brain_shared.config import BrainSettings


@dataclass(frozen=True, slots=True)
class _Manifest:
    """Minimal service manifest shape required by ``_start_grpc_runtime`` tests."""

    id: str

    @property
    def module_roots(self) -> frozenset[str]:
        """Satisfy resolver contract when patched resolver is not used."""
        return frozenset()


class _Registry:
    """Minimal registry shape required by ``_start_grpc_runtime`` tests."""

    def __init__(self, services: tuple[_Manifest, ...]) -> None:
        self._services = services

    def list_services(self) -> tuple[_Manifest, ...]:
        """Return configured service manifests."""
        return self._services


class _FakeServer:
    """Test double for gRPC server startup behavior."""

    def __init__(self, *, bound_port: int) -> None:
        self.bound_port = bound_port
        self.bound_address = ""
        self.started = False
        self.registered: list[str] = []
        self.generic_handlers: list[object] = []

    def add_insecure_port(self, address: str) -> int:
        """Record requested bind address and return configured port."""
        self.bound_address = address
        return self.bound_port

    def start(self) -> None:
        """Mark server as started."""
        self.started = True

    def add_generic_rpc_handlers(self, handlers: tuple[object, ...]) -> None:
        """Capture generic handlers registered by core/runtime reflection paths."""
        self.generic_handlers.extend(list(handlers))

    def add_registered_method_handlers(
        self, _service_name: str, _method_handlers: object
    ) -> None:
        """No-op compatibility hook used by newer generated gRPC registrars."""
        return None


def test_start_grpc_runtime_registers_services_and_binds() -> None:
    """Core runtime should register available service adapters and bind server."""
    settings = BrainSettings(
        components={"core_grpc": {"bind_host": "127.0.0.1", "bind_port": 50055}}
    )
    fake_server = _FakeServer(bound_port=50055)
    registry = _Registry(
        services=(_Manifest(id="service_a"), _Manifest(id="service_b"))
    )
    components = {"service_a": object(), "service_b": object()}

    def _server_factory(*_args, **_kwargs):
        return fake_server

    def _resolver(manifest: _Manifest):
        if manifest.id == "service_a":
            return lambda *, server, service: server.registered.append("service_a")
        if manifest.id == "service_b":
            return None
        return None

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("packages.brain_core.main.get_registry", lambda: registry)
    monkeypatch.setattr(
        "packages.brain_core.main._resolve_service_grpc_registrar", _resolver
    )
    try:
        server = _start_grpc_runtime(
            settings=settings,
            components=components,
            server_factory=_server_factory,
        )
    finally:
        monkeypatch.undo()

    assert server is fake_server
    assert fake_server.registered == ["service_a"]
    assert fake_server.bound_address == "127.0.0.1:50055"
    assert fake_server.started is True


def test_start_grpc_runtime_fails_when_bind_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Core runtime should fail hard when gRPC bind returns port 0."""
    settings = BrainSettings()
    fake_server = _FakeServer(bound_port=0)
    registry = _Registry(services=(_Manifest(id="service_a"),))
    components = {"service_a": object()}

    monkeypatch.setattr("packages.brain_core.main.get_registry", lambda: registry)
    monkeypatch.setattr(
        "packages.brain_core.main._resolve_service_grpc_registrar",
        lambda _manifest: (
            lambda *, server, service: server.registered.append("service_a")
        ),
    )

    with pytest.raises(RuntimeError, match="failed to bind core gRPC server"):
        _start_grpc_runtime(
            settings=settings,
            components=components,
            server_factory=lambda *_args, **_kwargs: fake_server,
        )


def test_start_grpc_runtime_enables_reflection_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Core runtime should enable gRPC reflection when explicitly configured."""
    settings = BrainSettings(
        components={
            "core_grpc": {
                "bind_host": "127.0.0.1",
                "bind_port": 50055,
                "enable_reflection": True,
            }
        }
    )
    fake_server = _FakeServer(bound_port=50055)
    registry = _Registry(services=(_Manifest(id="service_a"),))
    components = {"service_a": object()}
    calls: list[object] = []

    monkeypatch.setattr("packages.brain_core.main.get_registry", lambda: registry)
    monkeypatch.setattr(
        "packages.brain_core.main._resolve_service_grpc_registrar",
        lambda _manifest: (
            lambda *, server, service: server.registered.append("service_a")
        ),
    )
    monkeypatch.setattr(
        "packages.brain_core.main._enable_grpc_reflection",
        lambda *, server, generated_root: calls.append((server, generated_root)),
    )

    _start_grpc_runtime(
        settings=settings,
        components=components,
        server_factory=lambda *_args, **_kwargs: fake_server,
    )

    assert len(calls) == 1
