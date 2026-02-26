"""Tests for Postgres substrate readiness probes."""

from __future__ import annotations

from types import SimpleNamespace

import resources.substrates.postgres.boot as boot_module
from resources.substrates.postgres.health import ping


class _FakeConnection:
    """Minimal context-managed connection double capturing execute calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb

    def execute(self, statement, params=None) -> None:
        self.calls.append((str(statement), params))


class _FakeEngine:
    """Minimal engine double exposing ``connect``."""

    def __init__(self, conn: _FakeConnection) -> None:
        self._conn = conn

    def connect(self) -> _FakeConnection:
        return self._conn


def test_ping_applies_statement_timeout_via_set_config() -> None:
    """Ping should set statement timeout with set_config then run SELECT 1."""
    conn = _FakeConnection()
    engine = _FakeEngine(conn)

    assert ping(engine, timeout_seconds=1.2) is True
    assert conn.calls[0] == (
        "SELECT set_config('statement_timeout', :timeout_value, false)",
        {"timeout_value": "1200ms"},
    )
    assert conn.calls[1] == ("SELECT 1", None)


def test_ping_returns_false_when_connection_or_query_fails() -> None:
    """Ping should degrade cleanly on probe exceptions."""

    class _FailingConnection(_FakeConnection):
        def execute(self, statement, params=None) -> None:
            del statement, params
            raise RuntimeError("boom")

    engine = _FakeEngine(_FailingConnection())
    assert ping(engine, timeout_seconds=1.0) is False


def test_boot_readiness_uses_configured_health_timeout(monkeypatch) -> None:
    """Boot readiness should pass configured health timeout into ping."""
    captured: dict[str, object] = {}

    class _DisposableEngine:
        def dispose(self) -> None:
            captured["disposed"] = True

    def _fake_resolve_settings(_settings):
        return SimpleNamespace(health_timeout_seconds=2.5)

    def _fake_create_engine(settings):
        captured["settings"] = settings
        return _DisposableEngine()

    def _fake_ping(engine, *, timeout_seconds):
        captured["engine"] = engine
        captured["timeout_seconds"] = timeout_seconds
        return True

    monkeypatch.setattr(
        boot_module, "resolve_postgres_settings", _fake_resolve_settings
    )
    monkeypatch.setattr(boot_module, "create_postgres_engine", _fake_create_engine)
    monkeypatch.setattr(boot_module, "ping", _fake_ping)

    result = boot_module.is_ready(SimpleNamespace(settings=object()))
    assert result is True
    assert captured["timeout_seconds"] == 2.5
    assert captured["disposed"] is True
