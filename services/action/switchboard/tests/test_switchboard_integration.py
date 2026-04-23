"""Integration-style Switchboard tests at the Service->Resource boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass

from lib.shared.envelope import EnvelopeKind, new_meta, success
from resources.adapters.signal.adapter import (
    SignalAdapter,
    SignalCallbackRegistrationResult,
    SignalInboundCallback,
    SignalAdapterHealthResult,
    SignalSendMessageResult,
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
        self.registered_callback: SignalInboundCallback | None = None

    def register_callback(
        self,
        *,
        callback: SignalInboundCallback,
    ) -> SignalCallbackRegistrationResult:
        self.registered_callback = callback
        return SignalCallbackRegistrationResult(registered=True, detail="ok")

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
        return success(meta=_meta(), payload=1)

    def pop_queue(self, *, meta, component_id, queue):
        raise NotImplementedError

    def peek_queue(self, *, meta, component_id, queue):
        raise NotImplementedError

    def health(self, *, meta):
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


def test_ingest_signal_message_enqueues_operator_message() -> None:
    """Valid operator messages should be normalized and enqueued."""
    adapter = _FakeSignalAdapter()
    cache = _FakeCacheService()
    service = DefaultSwitchboardService(
        settings=SwitchboardServiceSettings(),
        identity=SwitchboardIdentitySettings(
            operator_signal_contact_e164="+12025550100",
            default_dial_code="+1",
        ),
        adapter=adapter,
        cache_service=cache,
    )
    body = json.dumps(
        {
            "data": {
                "account": "+12025550100",
                "envelope": {
                    "source": "+12025550100",
                    "sourceDevice": 1,
                    "timestamp": 1730000000000,
                    "dataMessage": {
                        "message": "hello",
                        "groupInfo": {"groupId": "group-123"},
                    },
                },
            }
        }
    )

    result = service.ingest_signal_message(
        meta=_meta(),
        raw_body_json=body,
    )

    assert result.ok is True
    assert len(cache.pushed) == 1
    assert cache.pushed[0]["queue"] == "signal_inbound"
    assert cache.pushed[0]["value"] == {
        "sender_e164": "+12025550100",
        "message_text": "hello",
        "timestamp_ms": 1730000000000,
        "source_device": "1",
        "source": "signal",
        "group_id": "group-123",
        "quote_target_timestamp_ms": None,
        "reaction_target_timestamp_ms": None,
        "reaction_emoji": None,
        "approval_intent": None,
        "reply_to_proposal_token": None,
        "reaction_to_proposal_token": None,
    }


def test_register_signal_callback_delegates_to_adapter() -> None:
    """Callback registration should call the owned adapter."""
    adapter = _FakeSignalAdapter()
    service = DefaultSwitchboardService(
        settings=SwitchboardServiceSettings(),
        identity=SwitchboardIdentitySettings(
            operator_signal_contact_e164="+12025550100",
            default_dial_code="+1",
        ),
        adapter=adapter,
        cache_service=_FakeCacheService(),
    )

    result = service.register_signal_callback(meta=_meta())

    assert result.ok is True
    assert adapter.registered_callback is not None
