"""Behavior tests for Relay inbound service implementation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import patch

from lib.shared.envelope import EnvelopeKind, failure, new_meta, success
from lib.shared.errors import dependency_error
from resources.adapters.signal import (
    SignalAdapter,
    SignalAdapterDependencyError,
    SignalAdapterHealthResult,
    SignalAdapterInternalError,
    SignalCallbackRegistrationResult,
    SignalInboundCallback,
    SignalSendMessageResult,
)
from services.effect.relay._outbound.domain import (
    ApprovalCorrelationPayload,
    HealthStatus as RelayOutboundHealthStatus,
    RouteNotificationResult,
)
from services.effect.relay._outbound.service import RelayOutboundService
from services.effect.relay._inbound import implementation as inbound_module
from services.effect.relay._inbound.config import (
    RelayInboundIdentitySettings,
    RelayInboundServiceSettings,
)
from services.effect.relay._inbound.implementation import DefaultRelayInboundService
from services.state.cache.domain import QueueEntry
from services.state.cache.service import CacheService


@dataclass(frozen=True)
class _QueueCall:
    """Captured queue push arguments."""

    component_id: str
    queue: str
    value: object


@dataclass(frozen=True)
class _QueuePopCall:
    """Captured queue pop arguments."""

    component_id: str
    queue: str


@dataclass(frozen=True)
class _CacheHealthStatus:
    """Minimal cache health payload consumed by Relay inbound."""

    service_ready: bool
    substrate_ready: bool
    detail: str


class _FakeSignalAdapter(SignalAdapter):
    """In-memory Signal adapter fake for Relay inbound behavior tests."""

    def __init__(self) -> None:
        self.registered_callbacks: list[SignalInboundCallback] = []
        self.raise_register: Exception | None = None
        self.health_result = SignalAdapterHealthResult(adapter_ready=True, detail="ok")

    def register_callback(
        self,
        *,
        callback: SignalInboundCallback,
    ) -> SignalCallbackRegistrationResult:
        self.registered_callbacks.append(callback)
        if self.raise_register is not None:
            raise self.raise_register
        return SignalCallbackRegistrationResult(registered=True, detail="registered")

    def health(self) -> SignalAdapterHealthResult:
        return self.health_result

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


class _FakeCacheService(CacheService):
    """In-memory Cache fake for Relay inbound behavior tests."""

    def __init__(self) -> None:
        self.queue_calls: list[_QueueCall] = []
        self.pop_calls: list[_QueuePopCall] = []
        self.push_errors = False
        self.pop_results: list[object] = []

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
                errors=[dependency_error("valkey unavailable")],
            )
        return success(meta=_meta(), payload=1)

    def pop_queue(self, *, meta, component_id, queue):
        del meta
        self.pop_calls.append(_QueuePopCall(component_id=component_id, queue=queue))
        next_value = self.pop_results.pop(0) if self.pop_results else None
        if next_value == "dependency_error":
            return failure(
                meta=_meta(), errors=[dependency_error("valkey unavailable")]
            )
        payload = next_value if isinstance(next_value, QueueEntry) else None
        return success(meta=_meta(), payload=payload)

    def peek_queue(self, *, meta, component_id, queue):
        del meta, component_id, queue
        raise NotImplementedError

    def health(self, *, meta):
        del meta
        return success(
            meta=_meta(),
            payload=_CacheHealthStatus(
                service_ready=True,
                substrate_ready=True,
                detail="ok",
            ),
        )


class _FakeRelayOutboundService(RelayOutboundService):
    """Relay outbound fake exposing outbound timestamp correlation lookups."""

    def __init__(self) -> None:
        self.timestamp_to_token: dict[tuple[str, int], str] = {}
        self.resolve_calls: list[tuple[object, str, int]] = []

    def route_notification(self, *, meta, **kwargs):
        del meta, kwargs
        return success(
            meta=_meta(),
            payload=RouteNotificationResult(
                decision="sent",
                delivered=True,
                detail="ok",
            ),
        )

    def route_approval_notification(self, *, meta, approval):
        del meta, approval
        return success(
            meta=_meta(),
            payload=RouteNotificationResult(
                decision="sent",
                delivered=True,
                detail="ok",
            ),
        )

    def flush_batch(self, *, meta, **kwargs):
        del meta, kwargs
        return success(
            meta=_meta(),
            payload=RouteNotificationResult(
                decision="sent",
                delivered=True,
                detail="ok",
            ),
        )

    def health(self, *, meta):
        del meta
        return success(
            meta=_meta(),
            payload=RelayOutboundHealthStatus(
                service_ready=True,
                adapter_ready=True,
                detail="ok",
            ),
        )

    def correlate_approval_response(self, *, meta, **kwargs):
        del meta
        return success(
            meta=_meta(),
            payload=ApprovalCorrelationPayload(
                actor=kwargs.get("actor", "operator"),
                channel=kwargs.get("channel", "signal"),
                message_text=kwargs.get("message_text", ""),
                approval_token=kwargs.get("approval_token", ""),
                reply_to_proposal_token=kwargs.get("reply_to_proposal_token", ""),
                reaction_to_proposal_token=kwargs.get("reaction_to_proposal_token", ""),
            ),
        )

    def resolve_approval_notification_proposal_token(
        self,
        *,
        meta,
        channel: str,
        target_timestamp_ms: int,
    ):
        self.resolve_calls.append((meta, channel, target_timestamp_ms))
        return success(
            meta=_meta(),
            payload=self.timestamp_to_token.get((channel, target_timestamp_ms)),
        )

    def poll_console_response(self, *, meta, wait_timeout_seconds: float = 0.0):
        del meta, wait_timeout_seconds
        return success(meta=_meta(), payload=None)


def _meta():
    """Build valid envelope metadata for Relay inbound tests."""
    return new_meta(kind=EnvelopeKind.EVENT, source="inbound", principal="operator")


def _service(
    *,
    operator_signal_contact_e164: str = "+12025550100",
    default_dial_code: str = "+1",
) -> tuple[
    DefaultRelayInboundService,
    _FakeSignalAdapter,
    _FakeCacheService,
    _FakeRelayOutboundService,
]:
    """Build Relay inbound with in-memory dependencies for tests."""
    adapter = _FakeSignalAdapter()
    cache = _FakeCacheService()
    outbound = _FakeRelayOutboundService()
    service = DefaultRelayInboundService(
        settings=RelayInboundServiceSettings(),
        identity=RelayInboundIdentitySettings(
            operator_signal_contact_e164=operator_signal_contact_e164,
            default_dial_code=default_dial_code,
        ),
        adapter=adapter,
        cache_service=cache,
        outbound_service=outbound,
    )
    return service, adapter, cache, outbound


def test_ingest_accepts_operator_message_and_enqueues_in_cas() -> None:
    """Operator messages should be accepted and queued."""
    service, _adapter, cache, _outbound = _service()
    body = json.dumps(
        {
            "data": {
                "account": "+12025550100",
                "envelope": {
                    "source": "2025550100",
                    "sourceNumber": "2025550100",
                    "sourceDevice": 7,
                    "timestamp": 1730000000000,
                    "dataMessage": {
                        "message": "hello",
                        "groupInfo": {"groupId": "group-123"},
                        "quote": {"timestamp": 101},
                        "reaction": {"targetSentTimestamp": 202},
                    },
                },
            }
        }
    )

    result = service.ingest_signal_message(meta=_meta(), raw_body_json=body)

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.accepted is True
    assert result.payload.value.queued is True
    assert result.payload.value.message is not None
    assert result.payload.value.message.sender_e164 == "+12025550100"
    assert result.payload.value.message.message_text == "hello"
    assert result.payload.value.message.source_device == "7"
    assert result.payload.value.message.group_id == "group-123"
    assert result.payload.value.message.quote_target_timestamp_ms == 101
    assert result.payload.value.message.reaction_target_timestamp_ms == 202
    assert len(cache.queue_calls) == 1
    assert cache.queue_calls[0].component_id == "service_relay"
    assert cache.queue_calls[0].queue == "signal_inbound"


def test_ingest_emits_verbose_logs_for_signal_approval_correlation() -> None:
    """Relay inbound should log raw, normalized, and resolved approval evidence."""
    service, _adapter, _cache, outbound = _service()
    outbound.timestamp_to_token[("signal", 101)] = "proposal-reply"
    outbound.timestamp_to_token[("signal", 202)] = "proposal-reaction"
    body = json.dumps(
        {
            "data": {
                "account": "+12025550100",
                "envelope": {
                    "source": "2025550100",
                    "timestamp": 1730000000000,
                    "dataMessage": {
                        "message": "approved",
                        "quote": {"timestamp": 101},
                        "reaction": {"emoji": "👍", "targetSentTimestamp": 202},
                    },
                },
            }
        }
    )

    inbound_meta = _meta()
    with patch.object(inbound_module._LOGGER, "verbose") as verbose_log:
        result = service.ingest_signal_message(meta=inbound_meta, raw_body_json=body)

    assert result.ok is True
    assert len(outbound.resolve_calls) == 2
    first_meta, first_channel, first_timestamp = outbound.resolve_calls[0]
    second_meta, second_channel, second_timestamp = outbound.resolve_calls[1]
    assert first_channel == "signal"
    assert first_timestamp == 101
    assert second_channel == "signal"
    assert second_timestamp == 202
    assert first_meta.trace_id == second_meta.trace_id == inbound_meta.trace_id
    assert first_meta.parent_id == second_meta.parent_id == inbound_meta.envelope_id
    assert first_meta.envelope_id != inbound_meta.envelope_id
    assert second_meta.envelope_id != inbound_meta.envelope_id
    assert verbose_log.call_args_list[0].args == (
        "inbound received raw signal payload",
    )
    completed = [
        call
        for call in verbose_log.call_args_list
        if call.args == ("inbound proposal token lookup completed",)
    ]
    assert len(completed) == 2
    assert {call.kwargs["extra"]["resolved_proposal_token"] for call in completed} == {
        "proposal-reply",
        "proposal-reaction",
    }


def test_ingest_ignores_non_operator_sender() -> None:
    """Messages from non-operator senders should not be queued."""
    service, _adapter, cache, _outbound = _service()
    body = json.dumps(
        {
            "data": {
                "account": "+17175550000",
                "envelope": {
                    "source": "+17175550000",
                    "timestamp": 1730000000000,
                    "dataMessage": {"message": "hello"},
                },
            }
        }
    )

    result = service.ingest_signal_message(meta=_meta(), raw_body_json=body)

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.accepted is False
    assert result.payload.value.queued is False
    assert cache.queue_calls == []


def test_ingest_rejects_invalid_json() -> None:
    """Invalid JSON should fail validation."""
    service, _adapter, cache, _outbound = _service()

    result = service.ingest_signal_message(meta=_meta(), raw_body_json="{")

    assert result.ok is False
    assert result.errors[0].category.value == "validation"
    assert cache.queue_calls == []


def test_ingest_correlates_quote_and_reaction_targets_to_proposal_tokens() -> None:
    """Quoted and reacted replies should carry resolved proposal tokens."""
    service, _adapter, cache, outbound = _service()
    outbound.timestamp_to_token[("signal", 101)] = "tok-quote"
    outbound.timestamp_to_token[("signal", 202)] = "tok-react"
    body = json.dumps(
        {
            "data": {
                "account": "+12025550100",
                "envelope": {
                    "source": "2025550100",
                    "sourceDevice": 7,
                    "timestamp": 1730000000000,
                    "dataMessage": {
                        "message": "yes",
                        "quote": {"timestamp": 101},
                        "reaction": {"targetSentTimestamp": 202},
                    },
                },
            }
        }
    )

    result = service.ingest_signal_message(meta=_meta(), raw_body_json=body)

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.message is not None
    assert result.payload.value.message.reply_to_proposal_token == "tok-quote"
    assert result.payload.value.message.reaction_to_proposal_token == "tok-react"
    assert cache.queue_calls[0].value["reply_to_proposal_token"] == "tok-quote"
    assert cache.queue_calls[0].value["reaction_to_proposal_token"] == "tok-react"


def test_ingest_uses_configured_dial_code_for_non_e164_inputs() -> None:
    """Non-E.164 values should normalize using configured default_dial_code."""
    service, _adapter, cache, _outbound = _service(
        operator_signal_contact_e164="2071234567",
        default_dial_code="+44",
    )
    body = json.dumps(
        {
            "data": {
                "source": "2071234567",
                "message": "hello",
                "timestamp": 1730000000000,
            }
        }
    )

    result = service.ingest_signal_message(meta=_meta(), raw_body_json=body)

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.message is not None
    assert result.payload.value.message.sender_e164 == "+442071234567"
    assert cache.queue_calls[0].value["sender_e164"] == "+442071234567"


def test_poll_operator_instruction_returns_normalized_message() -> None:
    """Poll should deserialize queued entries back into the DTO."""
    service, _adapter, cache, _outbound = _service()
    cache.pop_results.append(
        QueueEntry(
            component_id="service_relay",
            queue="signal_inbound",
            value={
                "sender_e164": "+12025550100",
                "message_text": "hello",
                "timestamp_ms": 1730000000000,
                "source_device": "1",
                "source": "signal",
                "group_id": None,
                "quote_target_timestamp_ms": None,
                "reaction_target_timestamp_ms": None,
                "reaction_emoji": None,
                "approval_intent": None,
                "reply_to_proposal_token": None,
                "reaction_to_proposal_token": None,
            },
        )
    )

    result = service.poll_operator_instruction(meta=_meta())

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value is not None
    assert result.payload.value.message_text == "hello"


def test_register_signal_callback_registers_adapter_callback() -> None:
    """Callback registration should delegate to the adapter."""
    service, adapter, _cache, _outbound = _service()

    result = service.register_signal_callback(meta=_meta())

    assert result.ok is True
    assert len(adapter.registered_callbacks) == 1


def test_register_signal_callback_maps_dependency_failures() -> None:
    """Adapter dependency failures should surface as envelope dependency errors."""
    service, adapter, _cache, _outbound = _service()
    adapter.raise_register = SignalAdapterDependencyError("signal unavailable")

    result = service.register_signal_callback(meta=_meta())

    assert result.ok is False
    assert result.errors[0].category.value == "dependency"


def test_build_signal_inbound_callback_maps_internal_failures_to_adapter_internal() -> (
    None
):
    """The in-process callback should escalate internal failures to the adapter."""
    service, _adapter, cache, _outbound = _service()
    cache.push_errors = True
    callback = service._build_signal_inbound_callback()  # type: ignore[attr-defined]
    body = json.dumps(
        {
            "data": {
                "account": "+12025550100",
                "envelope": {
                    "source": "+12025550100",
                    "timestamp": 1730000000000,
                    "dataMessage": {"message": "hello"},
                },
            }
        }
    )

    with patch.object(service, "ingest_signal_message") as ingest:
        ingest.side_effect = SignalAdapterInternalError("boom")
        try:
            callback(raw_body_json=body)
        except SignalAdapterInternalError as exc:
            assert str(exc) == "boom"
        else:
            raise AssertionError("expected SignalAdapterInternalError")
