"""Behavior tests for Cache Service implementation."""

from __future__ import annotations

from dataclasses import dataclass

from lib.shared.envelope import EnvelopeKind, new_meta
from resources.substrates.valkey import ValkeySubstrate
from services.state.cache.config import CacheSettings
from services.state.cache.implementation import DefaultCacheService


@dataclass
class _SetCall:
    key: str
    value: str
    ttl_seconds: int | None


@dataclass
class _KeyCall:
    key: str


@dataclass
class _PushCall:
    queue: str
    value: str


@dataclass
class _QueueCall:
    queue: str


class _FakeBackend(ValkeySubstrate):
    """In-memory backend fake for Cache behavior tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.queues: dict[str, list[str]] = {}
        self.set_calls: list[_SetCall] = []
        self.get_calls: list[_KeyCall] = []
        self.delete_calls: list[_KeyCall] = []
        self.push_calls: list[_PushCall] = []
        self.pop_calls: list[_QueueCall] = []
        self.peek_calls: list[_QueueCall] = []
        self.raise_on_set: Exception | None = None
        self.raise_on_get: Exception | None = None
        self.raise_on_push: Exception | None = None
        self.raise_on_ping: Exception | None = None

    def set_value(self, *, key: str, value: str, ttl_seconds: int | None) -> None:
        self.set_calls.append(_SetCall(key=key, value=value, ttl_seconds=ttl_seconds))
        if self.raise_on_set is not None:
            raise self.raise_on_set
        self.values[key] = value

    def get_value(self, *, key: str) -> str | None:
        self.get_calls.append(_KeyCall(key=key))
        if self.raise_on_get is not None:
            raise self.raise_on_get
        return self.values.get(key)

    def delete_value(self, *, key: str) -> bool:
        self.delete_calls.append(_KeyCall(key=key))
        return self.values.pop(key, None) is not None

    def push_queue(self, *, queue: str, value: str) -> int:
        self.push_calls.append(_PushCall(queue=queue, value=value))
        if self.raise_on_push is not None:
            raise self.raise_on_push
        self.queues.setdefault(queue, [])
        self.queues[queue].insert(0, value)
        return len(self.queues[queue])

    def pop_queue(self, *, queue: str) -> str | None:
        self.pop_calls.append(_QueueCall(queue=queue))
        values = self.queues.get(queue, [])
        if len(values) == 0:
            return None
        return values.pop()

    def peek_queue(self, *, queue: str) -> str | None:
        self.peek_calls.append(_QueueCall(queue=queue))
        values = self.queues.get(queue, [])
        if len(values) == 0:
            return None
        return values[-1]

    def ping(self) -> bool:
        if self.raise_on_ping is not None:
            raise self.raise_on_ping
        return True


def _service(
    *, allow_non_expiring_keys: bool = True
) -> tuple[DefaultCacheService, _FakeBackend]:
    """Build Cache with deterministic in-memory backend for tests."""
    backend = _FakeBackend()
    service = DefaultCacheService(
        settings=CacheSettings(allow_non_expiring_keys=allow_non_expiring_keys),
        backend=backend,
    )
    return service, backend


def _meta() -> object:
    """Return valid envelope metadata for Cache test requests."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_set_value_uses_default_ttl_and_component_scoped_key() -> None:
    """Set should apply default TTL and write under component-scoped Valkey key."""
    service, backend = _service()

    response = service.set_value(
        meta=_meta(),
        component_id="service_language",
        key="session",
        value={"a": 1},
    )

    assert response.ok is True
    assert backend.set_calls[0].key == "brain:cache:service_language:session"
    assert backend.set_calls[0].ttl_seconds == 300


def test_set_value_allows_non_expiring_when_ttl_zero() -> None:
    """TTL zero should create non-expiring entries when enabled."""
    service, backend = _service(allow_non_expiring_keys=True)

    response = service.set_value(
        meta=_meta(),
        component_id="service_language",
        key="session",
        value={"a": 1},
        ttl_seconds=0,
    )

    assert response.ok is True
    assert backend.set_calls[0].ttl_seconds is None


def test_set_value_rejects_non_expiring_when_disabled() -> None:
    """TTL zero should fail validation when non-expiring entries are disabled."""
    service, _backend = _service(allow_non_expiring_keys=False)

    response = service.set_value(
        meta=_meta(),
        component_id="service_language",
        key="session",
        value={"a": 1},
        ttl_seconds=0,
    )

    assert response.ok is False
    assert response.errors[0].category.value == "validation"


def test_get_value_returns_none_when_key_missing() -> None:
    """Get should return successful empty payload for missing keys."""
    service, _backend = _service()

    response = service.get_value(
        meta=_meta(),
        component_id="service_language",
        key="missing",
    )

    assert response.ok is True
    assert response.payload is not None
    assert response.payload.value is None


def test_get_value_decodes_json_payload() -> None:
    """Get should deserialize stored JSON into typed payload contract."""
    service, backend = _service()
    backend.values["brain:cache:service_language:session"] = '{"a": 1}'

    response = service.get_value(
        meta=_meta(),
        component_id="service_language",
        key="session",
    )

    assert response.ok is True
    assert response.payload is not None
    assert response.payload.value.value == {"a": 1}


def test_get_value_surfaces_internal_error_for_non_json_payload() -> None:
    """Non-JSON stored values should fail with explicit internal error."""
    service, backend = _service()
    backend.values["brain:cache:service_language:bad"] = "not-json"

    response = service.get_value(
        meta=_meta(),
        component_id="service_language",
        key="bad",
    )

    assert response.ok is False
    assert response.errors[0].category.value == "internal"


def test_queue_push_pop_peek_are_fifo_and_scoped() -> None:
    """Queue operations should preserve FIFO semantics within component namespace."""
    service, backend = _service()

    push_one = service.push_queue(
        meta=_meta(),
        component_id="service_language",
        queue="inbox",
        value={"id": 1},
    )
    push_two = service.push_queue(
        meta=_meta(),
        component_id="service_language",
        queue="inbox",
        value={"id": 2},
    )
    peek = service.peek_queue(
        meta=_meta(),
        component_id="service_language",
        queue="inbox",
    )
    pop_one = service.pop_queue(
        meta=_meta(),
        component_id="service_language",
        queue="inbox",
    )
    pop_two = service.pop_queue(
        meta=_meta(),
        component_id="service_language",
        queue="inbox",
    )

    assert push_one.ok is True
    assert push_two.ok is True
    assert push_two.payload is not None
    assert push_two.payload.value.size == 2
    assert backend.push_calls[0].queue == "brain:queue:service_language:inbox"
    assert peek.payload is not None
    assert peek.payload.value.value == {"id": 1}
    assert pop_one.payload is not None
    assert pop_one.payload.value.value == {"id": 1}
    assert pop_two.payload is not None
    assert pop_two.payload.value.value == {"id": 2}


def test_dependency_failures_map_to_dependency_error() -> None:
    """Substrate exceptions should map to dependency-category envelope failures."""
    service, backend = _service()
    backend.raise_on_push = RuntimeError("valkey unavailable")

    response = service.push_queue(
        meta=_meta(),
        component_id="service_language",
        queue="inbox",
        value={"id": 1},
    )

    assert response.ok is False
    assert response.errors[0].category.value == "dependency"


def test_health_degrades_when_ping_fails() -> None:
    """Health should report degraded substrate readiness when ping raises."""
    service, backend = _service()
    backend.raise_on_ping = RuntimeError("connection down")

    response = service.health(meta=_meta())

    assert response.ok is True
    assert response.payload is not None
    assert response.payload.value.substrate_ready is False
    assert "connection down" in response.payload.value.detail


def test_health_reports_ready_when_ping_succeeds() -> None:
    """Health should report fully ready when Valkey ping succeeds."""
    service, _backend = _service()

    response = service.health(meta=_meta())

    assert response.ok is True
    assert response.payload is not None
    assert response.payload.value.service_ready is True
    assert response.payload.value.substrate_ready is True


def test_delete_value_returns_true_when_key_exists() -> None:
    """Delete should return True when the key existed."""
    service, backend = _service()
    backend.values["brain:cache:service_language:x"] = '"v"'

    response = service.delete_value(
        meta=_meta(), component_id="service_language", key="x"
    )

    assert response.ok is True
    assert response.payload is not None
    assert response.payload.value is True


def test_delete_value_returns_false_when_key_missing() -> None:
    """Delete should return False when the key did not exist."""
    service, _backend = _service()

    response = service.delete_value(
        meta=_meta(), component_id="service_language", key="missing"
    )

    assert response.ok is True
    assert response.payload is not None
    assert response.payload.value is False


def test_set_value_with_explicit_ttl_passes_through() -> None:
    """Explicit positive TTL should be forwarded to backend unchanged."""
    service, backend = _service()

    response = service.set_value(
        meta=_meta(),
        component_id="service_language",
        key="tmp",
        value="data",
        ttl_seconds=60,
    )

    assert response.ok is True
    assert backend.set_calls[0].ttl_seconds == 60


def test_set_value_maps_substrate_error_to_dependency_failure() -> None:
    """Set value substrate errors should map to dependency-category errors."""
    service, backend = _service()
    backend.raise_on_set = RuntimeError("valkey write failed")

    response = service.set_value(
        meta=_meta(),
        component_id="service_language",
        key="k",
        value="v",
    )

    assert response.ok is False
    assert response.errors[0].category.value == "dependency"


def test_get_value_maps_substrate_error_to_dependency_failure() -> None:
    """Get value substrate errors should map to dependency-category errors."""
    service, backend = _service()
    backend.raise_on_get = RuntimeError("valkey read failed")

    response = service.get_value(meta=_meta(), component_id="service_language", key="k")

    assert response.ok is False
    assert response.errors[0].category.value == "dependency"


def test_pop_empty_queue_returns_none_payload() -> None:
    """Pop from an empty queue should return None payload."""
    service, _backend = _service()

    response = service.pop_queue(
        meta=_meta(), component_id="service_language", queue="empty"
    )

    assert response.ok is True
    assert response.payload is not None
    assert response.payload.value is None


def test_invalid_component_id_is_validation_error() -> None:
    """Malformed component IDs should fail validation."""
    service, _backend = _service()

    response = service.get_value(meta=_meta(), component_id="INVALID-ID!", key="k")

    assert response.ok is False
    assert response.errors[0].category.value == "validation"
