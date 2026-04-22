"""Unit tests for the Valkey client substrate wrapper."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import resources.substrates.valkey.valkey_substrate as valkey_substrate_module
from resources.substrates.valkey.config import ValkeySettings
from resources.substrates.valkey.valkey_substrate import ValkeyClientSubstrate


@dataclass
class _FakeValkeyClient:
    """In-memory fake implementing Valkey operations used by substrate wrapper."""

    values: dict[str, str] = field(default_factory=dict)
    queues: dict[str, list[str]] = field(default_factory=dict)

    def set(self, name: str, value: str, ex: int | None = None) -> bool:
        del ex
        self.values[name] = value
        return True

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def delete(self, name: str) -> int:
        if name in self.values:
            del self.values[name]
            return 1
        return 0

    def lpush(self, queue: str, value: str) -> int:
        self.queues.setdefault(queue, [])
        self.queues[queue].insert(0, value)
        return len(self.queues[queue])

    def rpop(self, queue: str) -> str | None:
        values = self.queues.get(queue, [])
        if len(values) == 0:
            return None
        return values.pop()

    def lindex(self, queue: str, index: int) -> str | None:
        values = self.queues.get(queue, [])
        if len(values) == 0:
            return None
        return values[index]

    def ping(self) -> bool:
        return True


def test_valkey_substrate_wraps_key_value_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Substrate should pass through set/get/delete semantics."""
    fake_client = _FakeValkeyClient()
    monkeypatch.setattr(
        valkey_substrate_module,
        "create_valkey_client",
        lambda settings: fake_client,
    )
    monkeypatch.setattr(
        valkey_substrate_module,
        "create_valkey_client_with_timeouts",
        lambda **kwargs: fake_client,
    )
    substrate = ValkeyClientSubstrate(settings=ValkeySettings())

    substrate.set_value(key="a", value="one", ttl_seconds=30)

    assert substrate.get_value(key="a") == "one"
    assert substrate.delete_value(key="a") is True
    assert substrate.get_value(key="a") is None


def test_valkey_substrate_implements_fifo_queue_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queue operations should use LPUSH + RPOP with tail peek."""
    fake_client = _FakeValkeyClient()
    monkeypatch.setattr(
        valkey_substrate_module,
        "create_valkey_client",
        lambda settings: fake_client,
    )
    monkeypatch.setattr(
        valkey_substrate_module,
        "create_valkey_client_with_timeouts",
        lambda **kwargs: fake_client,
    )
    substrate = ValkeyClientSubstrate(settings=ValkeySettings())

    substrate.push_queue(queue="q", value="first")
    size = substrate.push_queue(queue="q", value="second")

    assert size == 2
    assert substrate.peek_queue(queue="q") == "first"
    assert substrate.pop_queue(queue="q") == "first"
    assert substrate.pop_queue(queue="q") == "second"
    assert substrate.pop_queue(queue="q") is None


def test_valkey_substrate_reports_ping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ping should report wrapped Valkey liveness result."""
    fake_client = _FakeValkeyClient()
    monkeypatch.setattr(
        valkey_substrate_module,
        "create_valkey_client",
        lambda settings: fake_client,
    )
    monkeypatch.setattr(
        valkey_substrate_module,
        "create_valkey_client_with_timeouts",
        lambda **kwargs: fake_client,
    )
    substrate = ValkeyClientSubstrate(settings=ValkeySettings())

    assert substrate.ping() is True
