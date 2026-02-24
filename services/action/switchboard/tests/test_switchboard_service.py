"""Behavior tests for Switchboard Service implementation."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from time import time

from packages.brain_shared.envelope import EnvelopeKind, failure, new_meta, success
from packages.brain_shared.errors import dependency_error
from resources.adapters.signal import (
    SignalAdapter,
    SignalAdapterDependencyError,
    SignalAdapterHealthResult,
    SignalWebhookRegistrationResult,
)
from services.action.switchboard.config import (
    SwitchboardIdentitySettings,
    SwitchboardServiceSettings,
)
from services.action.switchboard.implementation import DefaultSwitchboardService
from services.state.cache_authority.service import CacheAuthorityService


@dataclass(frozen=True)
class _RegisterCall:
    callback_url: str
    shared_secret: str


@dataclass(frozen=True)
class _QueueCall:
    component_id: str
    queue: str
    value: object


@dataclass(frozen=True)
class _QueueDepth:
    component_id: str
    queue: str
    size: int


@dataclass(frozen=True)
class _CacheHealthStatus:
    service_ready: bool
    substrate_ready: bool
    detail: str


class _FakeSignalAdapter(SignalAdapter):
    """In-memory Signal adapter fake for Switchboard behavior tests."""

    def __init__(self) -> None:
        self.register_calls: list[_RegisterCall] = []
        self.raise_register: Exception | None = None
        self.health_result = SignalAdapterHealthResult(adapter_ready=True, detail="ok")

    def register_webhook(
        self,
        *,
        callback_url: str,
        shared_secret: str,
    ) -> SignalWebhookRegistrationResult:
        self.register_calls.append(
            _RegisterCall(callback_url=callback_url, shared_secret=shared_secret)
        )
        if self.raise_register is not None:
            raise self.raise_register
        return SignalWebhookRegistrationResult(registered=True, detail="registered")

    def health(self) -> SignalAdapterHealthResult:
        return self.health_result


class _FakeCacheService(CacheAuthorityService):
    """In-memory CAS fake for Switchboard behavior tests."""

    def __init__(self) -> None:
        self.queue_calls: list[_QueueCall] = []
        self.push_errors: bool = False

    def set_value(self, *, meta, component_id, key, value, ttl_seconds=None):
        del meta, component_id, key, value, ttl_seconds
        raise NotImplementedError

    def get_value(self, *, meta, component_id, key):
        del meta, component_id, key
        raise NotImplementedError

    def delete_value(self, *, meta, component_id, key):
        del meta, component_id, key
        raise NotImplementedError

    def push_queue(self, *, meta, component_id, queue, value):
        del meta
        self.queue_calls.append(
            _QueueCall(component_id=component_id, queue=queue, value=value)
        )
        if self.push_errors:
            return failure(
                meta=_meta(),
                errors=[dependency_error("redis unavailable")],
            )
        return success(
            meta=_meta(),
            payload=_QueueDepth(component_id=component_id, queue=queue, size=1),
        )

    def pop_queue(self, *, meta, component_id, queue):
        del meta, component_id, queue
        raise NotImplementedError

    def peek_queue(self, *, meta, component_id, queue):
        del meta, component_id, queue
        raise NotImplementedError

    def health(self, *, meta):
        del meta
        return success(
            meta=_meta(),
            payload=_CacheHealthStatus(
                service_ready=True, substrate_ready=True, detail="ok"
            ),
        )


def _meta():
    """Build valid envelope metadata for Switchboard tests."""
    return new_meta(kind=EnvelopeKind.EVENT, source="switchboard", principal="operator")


def _signature(secret: str, timestamp: int, body: str) -> str:
    """Return canonical v1 webhook signature for tests."""
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=f"{timestamp}.{body}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def _service(
    *,
    operator_signal_e164: str = "+12025550100",
    webhook_secret: str = "super-secret",
) -> tuple[DefaultSwitchboardService, _FakeSignalAdapter, _FakeCacheService]:
    """Build Switchboard with in-memory dependencies for tests."""
    adapter = _FakeSignalAdapter()
    cache = _FakeCacheService()
    service = DefaultSwitchboardService(
        settings=SwitchboardServiceSettings(),
        identity=SwitchboardIdentitySettings(
            operator_signal_e164=operator_signal_e164,
            default_country_code="US",
            webhook_shared_secret=webhook_secret,
        ),
        adapter=adapter,
        cache_service=cache,
    )
    return service, adapter, cache


def test_ingest_accepts_operator_message_and_enqueues_in_cas() -> None:
    """Operator messages with valid signature should be accepted and queued."""
    service, _adapter, cache = _service()
    body = json.dumps(
        {
            "data": {
                "source": "2025550100",
                "message": "hello",
                "timestamp": int(time() * 1000),
            }
        }
    )
    timestamp = int(time())

    result = service.ingest_signal_webhook(
        meta=_meta(),
        raw_body_json=body,
        header_timestamp=str(timestamp),
        header_signature=_signature("super-secret", timestamp, body),
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.accepted is True
    assert result.payload.value.queued is True
    assert len(cache.queue_calls) == 1
    assert cache.queue_calls[0].component_id == "service_switchboard"
    assert cache.queue_calls[0].queue == "signal_inbound"


def test_ingest_rejects_invalid_signature() -> None:
    """Invalid signatures should fail ingress as policy violations."""
    service, _adapter, cache = _service()
    body = json.dumps(
        {"data": {"source": "+12025550100", "message": "hello", "timestamp": 1}}
    )

    result = service.ingest_signal_webhook(
        meta=_meta(),
        raw_body_json=body,
        header_timestamp="1",
        header_signature="bad-signature",
    )

    assert result.ok is False
    assert result.errors[0].category.value == "policy"
    assert len(cache.queue_calls) == 0


def test_ingest_rejects_non_operator_sender() -> None:
    """Non-operator sender messages should be explicitly rejected, not queued."""
    service, _adapter, cache = _service()
    body = json.dumps(
        {
            "data": {
                "source": "+12025550199",
                "message": "hello",
                "timestamp": int(time() * 1000),
            }
        }
    )
    timestamp = int(time())

    result = service.ingest_signal_webhook(
        meta=_meta(),
        raw_body_json=body,
        header_timestamp=str(timestamp),
        header_signature=_signature("super-secret", timestamp, body),
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.accepted is False
    assert result.payload.value.reason == "sender is not configured operator"
    assert len(cache.queue_calls) == 0


def test_ingest_ignores_non_message_payload() -> None:
    """Webhook payloads without message text should be ignored without errors."""
    service, _adapter, cache = _service()
    body = json.dumps({"data": {"source": "+12025550100", "timestamp": 1}})
    timestamp = int(time())

    result = service.ingest_signal_webhook(
        meta=_meta(),
        raw_body_json=body,
        header_timestamp=str(timestamp),
        header_signature=_signature("super-secret", timestamp, body),
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.accepted is False
    assert result.payload.value.reason == "non-message payload"
    assert len(cache.queue_calls) == 0


def test_ingest_propagates_cas_enqueue_failures() -> None:
    """CAS failures should be returned as envelope errors from Switchboard."""
    service, _adapter, cache = _service()
    cache.push_errors = True
    body = json.dumps(
        {
            "data": {
                "source": "+12025550100",
                "message": "hello",
                "timestamp": int(time() * 1000),
            }
        }
    )
    timestamp = int(time())

    result = service.ingest_signal_webhook(
        meta=_meta(),
        raw_body_json=body,
        header_timestamp=str(timestamp),
        header_signature=_signature("super-secret", timestamp, body),
    )

    assert result.ok is False
    assert result.errors[0].category.value == "dependency"


def test_register_signal_webhook_uses_configured_secret() -> None:
    """Registration should pass callback URL + resolved secret to adapter."""
    service, adapter, _cache = _service(webhook_secret="configured-secret")

    result = service.register_signal_webhook(
        meta=_meta(),
        callback_url="https://example.com/switchboard/signal",
        shared_secret_ref="profile.webhook_shared_secret",
    )

    assert result.ok is True
    assert len(adapter.register_calls) == 1
    assert (
        adapter.register_calls[0].callback_url
        == "https://example.com/switchboard/signal"
    )
    assert adapter.register_calls[0].shared_secret == "configured-secret"


def test_register_signal_webhook_maps_dependency_failures() -> None:
    """Adapter dependency failures should map to dependency envelope errors."""
    service, adapter, _cache = _service()
    adapter.raise_register = SignalAdapterDependencyError("signal unavailable")

    result = service.register_signal_webhook(
        meta=_meta(),
        callback_url="https://example.com/switchboard/signal",
        shared_secret_ref="profile.webhook_shared_secret",
    )

    assert result.ok is False
    assert result.errors[0].category.value == "dependency"


def test_health_reports_adapter_and_cas_readiness() -> None:
    """Health should include aggregated adapter and CAS readiness state."""
    service, adapter, _cache = _service()
    adapter.health_result = SignalAdapterHealthResult(
        adapter_ready=False, detail="degraded"
    )

    result = service.health(meta=_meta())

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.service_ready is True
    assert result.payload.value.adapter_ready is False
    assert result.payload.value.cas_ready is True
