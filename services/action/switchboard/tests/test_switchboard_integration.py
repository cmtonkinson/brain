"""Integration-style Switchboard tests at the Service->Resource boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

from packages.brain_shared.envelope import EnvelopeKind, new_meta
from resources.adapters.signal.adapter import (
    SignalAdapter,
    SignalAdapterHealthResult,
    SignalSendMessageResult,
    SignalWebhookRegistrationResult,
)
from services.action.switchboard.config import (
    SwitchboardIdentitySettings,
    SwitchboardServiceSettings,
)
from services.action.switchboard.implementation import DefaultSwitchboardService
from services.state.cache_authority.service import CacheAuthorityService


@dataclass(frozen=True)
class _CacheHealthPayload:
    """Minimal payload shape consumed by Switchboard health aggregation."""

    service_ready: bool
    substrate_ready: bool
    detail: str


class _FakeSignalAdapter(SignalAdapter):
    """Signal adapter fake with deterministic registration and health behavior."""

    def __init__(self) -> None:
        self.registered_callback_url: str = ""

    def register_webhook(
        self,
        *,
        callback_url: str,
        shared_secret: str,
        operator_e164: str,
    ) -> SignalWebhookRegistrationResult:
        del shared_secret, operator_e164
        self.registered_callback_url = callback_url
        return SignalWebhookRegistrationResult(registered=True, detail="ok")

    def health(self) -> SignalAdapterHealthResult:
        return SignalAdapterHealthResult(adapter_ready=True, detail="ok")

    def send_message(
        self,
        *,
        sender_e164: str,
        recipient_e164: str,
        message: str,
    ) -> SignalSendMessageResult:
        del sender_e164, recipient_e164, message
        return SignalSendMessageResult(
            delivered=True,
            recipient_e164="+12025550100",
            sender_e164="+12025550101",
            detail="sent",
        )


class _FakeCacheService(CacheAuthorityService):
    """Cache service fake capturing pushed queue payloads."""

    def __init__(self) -> None:
        self.pushed: list[dict[str, object]] = []

    def set_value(self, *, meta, component_id, key, value, ttl_seconds=None):
        raise NotImplementedError

    def get_value(self, *, meta, component_id, key):
        raise NotImplementedError

    def delete_value(self, *, meta, component_id, key):
        raise NotImplementedError

    def push_queue(self, *, meta, component_id, queue, value):
        del meta, component_id
        self.pushed.append({"queue": queue, "value": value})
        from packages.brain_shared.envelope import success

        return success(meta=_meta(), payload=1)

    def pop_queue(self, *, meta, component_id, queue):
        raise NotImplementedError

    def peek_queue(self, *, meta, component_id, queue):
        raise NotImplementedError

    def health(self, *, meta):
        from packages.brain_shared.envelope import success

        return success(
            meta=meta,
            payload=_CacheHealthPayload(
                service_ready=True,
                substrate_ready=True,
                detail="ok",
            ),
        )


def _meta():
    """Build deterministic envelope metadata for service tests."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def _signature(secret: str, timestamp: int, body: str) -> str:
    """Return webhook signature header value for payload."""
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def test_ingest_signal_webhook_enqueues_operator_message() -> None:
    """Valid signed operator messages should be normalized and enqueued."""
    adapter = _FakeSignalAdapter()
    cache = _FakeCacheService()
    service = DefaultSwitchboardService(
        settings=SwitchboardServiceSettings(signature_tolerance_seconds=300),
        identity=SwitchboardIdentitySettings(
            operator_signal_e164="+12025550100",
            default_country_code="US",
            webhook_shared_secret="secret",
        ),
        adapter=adapter,
        cache_service=cache,
    )
    body = json.dumps(
        {
            "data": {
                "source": "+12025550100",
                "message": "hello",
                "timestamp": 1730000000000,
            }
        }
    )
    now_ts = int(_meta().timestamp.timestamp())

    result = service.ingest_signal_webhook(
        meta=_meta(),
        raw_body_json=body,
        header_timestamp=str(now_ts),
        header_signature=_signature("secret", now_ts, body),
    )

    assert result.ok is True
    assert len(cache.pushed) == 1
    assert cache.pushed[0]["queue"] == "signal_inbound"


def test_register_signal_webhook_delegates_to_adapter() -> None:
    """Webhook registration should call owned adapter with callback URL."""
    adapter = _FakeSignalAdapter()
    service = DefaultSwitchboardService(
        settings=SwitchboardServiceSettings(),
        identity=SwitchboardIdentitySettings(
            operator_signal_e164="+12025550100",
            default_country_code="US",
            webhook_shared_secret="secret",
        ),
        adapter=adapter,
        cache_service=_FakeCacheService(),
    )

    result = service.register_signal_webhook(
        meta=_meta(),
        callback_url="http://localhost:8091/v1/inbound/signal/webhook",
    )

    assert result.ok is True
    assert adapter.registered_callback_url.endswith("/webhook")
