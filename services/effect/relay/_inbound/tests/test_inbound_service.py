"""Behavior tests for Relay inbound service implementation."""

from __future__ import annotations

from dataclasses import dataclass

from lib.shared.envelope import EnvelopeKind, failure, new_meta, success
from lib.shared.errors import dependency_error
from lib.shared.inbound_adapter import (
    InboundAdapterDependencyError,
    InboundAdapterHealthResult,
    InboundCallback,
    InboundCallbackRegistrationResult,
)
from lib.shared.inbound_message import (
    InboundApproval,
    InboundMessage,
    InboundMessageRef,
    InboundReaction,
    InboundSender,
)
from resources.adapters.signal import (
    SignalAdapter,
    SignalSendMessageResult,
)
from services.effect.relay._outbound.domain import (
    ApprovalCorrelationPayload,
    HealthStatus as RelayOutboundHealthStatus,
    RouteNotificationResult,
)
from services.effect.relay._outbound.service import RelayOutboundService
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


class _FakeSignalAdapter(SignalAdapter):
    """In-memory Signal adapter fake for Relay inbound behavior tests."""

    def __init__(self) -> None:
        self.registered_callbacks: list[InboundCallback] = []
        self.raise_register: Exception | None = None

    def register_callback(self, *, callback: InboundCallback):
        self.registered_callbacks.append(callback)
        if self.raise_register is not None:
            raise self.raise_register
        return InboundCallbackRegistrationResult(registered=True, detail="registered")

    def health(self) -> InboundAdapterHealthResult:
        return InboundAdapterHealthResult(adapter_ready=True, detail="ok")

    def send_message(self, *, sender_e164: str, recipient_e164: str, message: str):
        del sender_e164, recipient_e164, message
        return SignalSendMessageResult(
            delivered=True,
            recipient_e164="+12025550100",
            sender_e164="+12025550101",
            detail="sent",
        )

    def mint_slash_authenticity_proof(self, *, channel: str, message_text: str):
        del channel, message_text
        raise NotImplementedError


class _FakeCacheService(CacheService):
    """In-memory Cache fake for Relay inbound behavior tests."""

    def __init__(self) -> None:
        self.queue_calls: list[_QueueCall] = []
        self.pop_results: list[object] = []
        self.push_errors = False

    def set_value(self, *, meta, component_id, key, value, ttl_seconds=None):
        raise NotImplementedError

    def get_value(self, *, meta, component_id, key):
        raise NotImplementedError

    def delete_value(self, *, meta, component_id, key):
        raise NotImplementedError

    def push_queue(self, *, meta, component_id, queue, value):
        del meta
        self.queue_calls.append(
            _QueueCall(component_id=component_id, queue=queue, value=value)
        )
        if self.push_errors:
            return failure(
                meta=_meta(), errors=[dependency_error("valkey unavailable")]
            )
        return success(meta=_meta(), payload=1)

    def pop_queue(self, *, meta, component_id, queue):
        del meta, component_id, queue
        next_value = self.pop_results.pop(0) if self.pop_results else None
        payload = next_value if isinstance(next_value, QueueEntry) else None
        return success(meta=_meta(), payload=payload)

    def peek_queue(self, *, meta, component_id, queue):
        raise NotImplementedError

    def health(self, *, meta):
        del meta
        return success(
            meta=_meta(),
            payload={"service_ready": True, "substrate_ready": True, "detail": "ok"},
        )


class _FakeRelayOutboundService(RelayOutboundService):
    """Relay outbound fake exposing outbound timestamp correlation lookups."""

    def __init__(self) -> None:
        self.timestamp_to_token: dict[tuple[str, int], str] = {}

    def route_notification(self, *, meta, **kwargs):
        del meta, kwargs
        return success(
            meta=_meta(),
            payload=RouteNotificationResult(
                decision="sent", delivered=True, detail="ok"
            ),
        )

    def route_approval_notification(self, *, meta, approval):
        del meta, approval
        return success(
            meta=_meta(),
            payload=RouteNotificationResult(
                decision="sent", delivered=True, detail="ok"
            ),
        )

    def flush_batch(self, *, meta, **kwargs):
        del meta, kwargs
        return success(
            meta=_meta(),
            payload=RouteNotificationResult(
                decision="sent", delivered=True, detail="ok"
            ),
        )

    def health(self, *, meta):
        del meta
        return success(
            meta=_meta(),
            payload=RelayOutboundHealthStatus(
                service_ready=True, adapter_ready=True, detail="ok"
            ),
        )

    def correlate_approval_response(self, *, meta, **kwargs):
        del meta
        return success(
            meta=_meta(),
            payload=ApprovalCorrelationPayload(
                actor=kwargs.get("actor", "operator"),
                channel=kwargs.get("channel", "signal"),
            ),
        )

    def resolve_approval_notification_proposal_token(
        self, *, meta, channel: str, target_timestamp_ms: int
    ):
        del meta
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


def _service():
    """Build Relay inbound with in-memory dependencies for tests."""
    adapter = _FakeSignalAdapter()
    cache = _FakeCacheService()
    outbound = _FakeRelayOutboundService()
    service = DefaultRelayInboundService(
        settings=RelayInboundServiceSettings(),
        identity=RelayInboundIdentitySettings(
            operator_contact_e164="+12025550100", default_dial_code="+1"
        ),
        inbound_adapters=(adapter,),
        cache_service=cache,
        outbound_service=outbound,
    )
    return service, adapter, cache, outbound


def test_ingest_inbound_message_enqueues_single_operator_queue() -> None:
    """Relay should enqueue normalized messages without channel-specific queues."""
    service, _adapter, cache, _outbound = _service()
    message = InboundMessage(
        channel="signal",
        sender=InboundSender(e164="+12025550100"),
        message_text="hello",
        timestamp_ms=1730000000000,
    )

    result = service.ingest_inbound_message(meta=_meta(), message=message)

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.queued is True
    assert cache.queue_calls[0].queue == "operator_inbound"
    assert cache.queue_calls[0].value["channel"] == "signal"


def test_ingest_resolves_reply_and_reaction_proposal_tokens() -> None:
    """Relay may correlate normalized reply/reaction references to proposals."""
    service, _adapter, cache, outbound = _service()
    outbound.timestamp_to_token[("signal", 101)] = "tok-reply"
    outbound.timestamp_to_token[("signal", 202)] = "tok-react"
    message = InboundMessage(
        channel="signal",
        sender=InboundSender(e164="+12025550100"),
        message_text="approved",
        timestamp_ms=1730000000000,
        reply_to=InboundMessageRef(timestamp_ms=101),
        reaction=InboundReaction(text="👍", target=InboundMessageRef(timestamp_ms=202)),
        approval=InboundApproval(intent="approve", source="reaction"),
    )

    result = service.ingest_inbound_message(meta=_meta(), message=message)

    assert result.ok is True
    assert cache.queue_calls[0].value["reply_to_proposal_token"] == "tok-reply"
    assert cache.queue_calls[0].value["reaction_to_proposal_token"] == "tok-react"


def test_poll_operator_instruction_returns_inbound_message() -> None:
    """Poll should deserialize queued DTO payloads."""
    service, _adapter, cache, _outbound = _service()
    message = InboundMessage(channel="console", message_text="hello", timestamp_ms=1)
    cache.pop_results.append(
        QueueEntry(
            component_id="service_relay",
            queue="operator_inbound",
            value=message.relay_payload(),
        )
    )

    result = service.poll_operator_instruction(meta=_meta())

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.channel == "console"
    assert result.payload.value.message_text == "hello"


def test_register_inbound_callbacks_registers_configured_adapters() -> None:
    """Callback registration should delegate to adapters."""
    service, adapter, _cache, _outbound = _service()

    result = service.register_inbound_callbacks(meta=_meta())

    assert result.ok is True
    assert len(adapter.registered_callbacks) == 1


def test_register_inbound_callbacks_maps_dependency_failures() -> None:
    """Adapter dependency failures should surface as envelope dependency errors."""
    service, adapter, _cache, _outbound = _service()
    adapter.raise_register = InboundAdapterDependencyError("signal unavailable")

    result = service.register_inbound_callbacks(meta=_meta())

    assert result.ok is False
    assert result.errors[0].category.value == "dependency"
