"""Behavior tests for Attention Router Service implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from packages.brain_shared.envelope import EnvelopeKind, failure, new_meta, success
from packages.brain_shared.errors import dependency_error
from resources.adapters.signal import (
    SignalAdapter,
    SignalAdapterDependencyError,
    SignalAdapterHealthResult,
    SignalSendMessageResult,
    SignalWebhookRegistrationResult,
)
from services.action.attention_router.config import AttentionRouterServiceSettings
from services.action.attention_router.domain import ApprovalNotificationPayload
from services.action.attention_router.implementation import (
    DefaultAttentionRouterService,
)
from services.state.cache_authority.domain import CacheEntry
from services.state.cache_authority.service import CacheAuthorityService


@dataclass(frozen=True)
class _SendCall:
    sender_e164: str
    recipient_e164: str
    message: str


class _FakeSignalAdapter(SignalAdapter):
    """In-memory Signal adapter fake for Attention Router behavior tests."""

    def __init__(self) -> None:
        self.send_calls: list[_SendCall] = []
        self.raise_send: Exception | None = None
        self.health_result = SignalAdapterHealthResult(adapter_ready=True, detail="ok")

    def register_webhook(
        self,
        *,
        callback_url: str,
        shared_secret: str,
        operator_e164: str,
    ) -> SignalWebhookRegistrationResult:
        del callback_url, shared_secret, operator_e164
        return SignalWebhookRegistrationResult(registered=True, detail="ok")

    def health(self) -> SignalAdapterHealthResult:
        return self.health_result

    def send_message(
        self,
        *,
        sender_e164: str,
        recipient_e164: str,
        message: str,
    ) -> SignalSendMessageResult:
        self.send_calls.append(
            _SendCall(
                sender_e164=sender_e164,
                recipient_e164=recipient_e164,
                message=message,
            )
        )
        if self.raise_send is not None:
            raise self.raise_send
        return SignalSendMessageResult(
            delivered=True,
            recipient_e164=recipient_e164,
            sender_e164=sender_e164,
            detail="sent",
            sent_timestamp_ms=123,
        )

    def resolve_approval_notification_proposal_token(
        self,
        *,
        meta,
        channel: str,
        target_timestamp_ms: int,
    ):
        del meta, channel, target_timestamp_ms
        raise NotImplementedError


class _FakeCacheAuthorityService(CacheAuthorityService):
    """In-memory CAS fake for approval correlation persistence tests."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], object] = {}
        self.fail_set = False
        self.fail_get = False

    def set_value(self, *, meta, component_id: str, key: str, value, ttl_seconds=None):
        del meta
        if self.fail_set:
            return failure(meta=_meta(), errors=[dependency_error("cache unavailable")])
        self.values[(component_id, key)] = value
        return success(
            meta=_meta(),
            payload=CacheEntry(
                component_id=component_id,
                key=key,
                value=value,
                ttl_seconds=ttl_seconds,
            ),
        )

    def get_value(self, *, meta, component_id: str, key: str):
        del meta
        if self.fail_get:
            return failure(meta=_meta(), errors=[dependency_error("cache unavailable")])
        value = self.values.get((component_id, key))
        if value is None:
            return success(meta=_meta(), payload=None)
        return success(
            meta=_meta(),
            payload=CacheEntry(
                component_id=component_id,
                key=key,
                value=value,
                ttl_seconds=None,
            ),
        )

    def delete_value(self, *, meta, component_id: str, key: str):
        del meta
        self.values.pop((component_id, key), None)
        return success(meta=_meta(), payload=True)

    def push_queue(self, *, meta, component_id: str, queue: str, value):
        raise NotImplementedError

    def pop_queue(self, *, meta, component_id: str, queue: str):
        raise NotImplementedError

    def peek_queue(self, *, meta, component_id: str, queue: str):
        raise NotImplementedError

    def health(self, *, meta):
        raise NotImplementedError


def _meta():
    """Build valid envelope metadata for Attention Router tests."""
    return new_meta(
        kind=EnvelopeKind.EVENT, source="attention-router", principal="operator"
    )


def _service() -> tuple[
    DefaultAttentionRouterService, _FakeSignalAdapter, _FakeCacheAuthorityService
]:
    """Build Attention Router with in-memory dependencies for tests."""
    adapter = _FakeSignalAdapter()
    cache = _FakeCacheAuthorityService()
    service = DefaultAttentionRouterService(
        settings=AttentionRouterServiceSettings(
            default_channel="signal",
            dedupe_window_seconds=120,
            rate_limit_window_seconds=60,
            rate_limit_max_per_window=2,
            batch_summary_max_items=2,
        ),
        signal_adapter=adapter,
        operator_signal_contact_e164="+12025550100",
        signal_receive_e164="+12025550101",
        cache_authority_service=cache,
    )
    return service, adapter, cache


def test_route_notification_delivers_signal_message() -> None:
    """Signal notification should be delivered with resolved defaults."""
    service, adapter, _cache = _service()

    result = service.route_notification(meta=_meta(), message="hello")

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.decision == "sent"
    assert result.payload.value.delivered is True
    assert len(adapter.send_calls) == 1
    assert adapter.send_calls[0].recipient_e164 == "+12025550100"


def test_route_notification_suppresses_recent_dedupe_key() -> None:
    """Same dedupe key within configured window should be suppressed."""
    service, adapter, _cache = _service()

    first = service.route_notification(
        meta=_meta(),
        message="hello",
        dedupe_key="task:123",
    )
    second = service.route_notification(
        meta=_meta(),
        message="hello",
        dedupe_key="task:123",
    )

    assert first.ok is True
    assert second.ok is True
    assert second.payload is not None
    assert second.payload.value.decision == "suppressed"
    assert second.payload.value.suppressed_reason == "dedupe_window"
    assert len(adapter.send_calls) == 1


def test_route_notification_batches_when_batch_key_present() -> None:
    """Batch-keyed notifications should queue until explicitly flushed."""
    service, adapter, _cache = _service()

    queued = service.route_notification(
        meta=_meta(),
        message="hello",
        batch_key="digest",
    )

    assert queued.ok is True
    assert queued.payload is not None
    assert queued.payload.value.decision == "batched"
    assert queued.payload.value.batched_count == 1
    assert len(adapter.send_calls) == 0


def test_flush_batch_delivers_consolidated_summary() -> None:
    """Flushing a pending batch should deliver one summary notification."""
    service, adapter, _cache = _service()
    service.route_notification(meta=_meta(), message="first", batch_key="digest")
    service.route_notification(meta=_meta(), message="second", batch_key="digest")
    service.route_notification(meta=_meta(), message="third", batch_key="digest")

    flushed = service.flush_batch(meta=_meta(), batch_key="digest")

    assert flushed.ok is True
    assert flushed.payload is not None
    assert flushed.payload.value.decision == "sent"
    assert len(adapter.send_calls) == 1
    assert "... and 1 more" in adapter.send_calls[0].message


def test_route_notification_propagates_signal_dependency_errors() -> None:
    """Signal dependency errors should map to dependency envelope failures."""
    service, adapter, _cache = _service()
    adapter.raise_send = SignalAdapterDependencyError("signal unavailable")

    result = service.route_notification(meta=_meta(), message="hello")

    assert result.ok is False
    assert result.errors[0].category.value == "dependency"


def test_route_notification_suppresses_when_rate_limited() -> None:
    """Exceeding channel/recipient send window should suppress delivery."""
    service, adapter, _cache = _service()

    service.route_notification(meta=_meta(), message="one")
    service.route_notification(meta=_meta(), message="two")
    limited = service.route_notification(meta=_meta(), message="three")

    assert limited.ok is True
    assert limited.payload is not None
    assert limited.payload.value.decision == "suppressed"
    assert limited.payload.value.suppressed_reason == "rate_limited"
    assert len(adapter.send_calls) == 2


def test_route_approval_notification_formats_policy_payload() -> None:
    """Approval payload routing should emit policy token details via Signal."""
    service, adapter, cache = _service()

    result = service.route_approval_notification(
        meta=_meta(),
        approval=ApprovalNotificationPayload(
            proposal_token="tok-123",
            capability_id="cap.demo",
            capability_version="1.0.0",
            summary="Need approval",
            actor="operator",
            channel="signal",
            trace_id="trace-1",
            invocation_id="inv-1",
            expires_at=datetime(2026, 2, 25, 12, 0, 0, tzinfo=UTC),
        ),
    )

    assert result.ok is True
    assert len(adapter.send_calls) == 1
    assert "Token: tok-123" in adapter.send_calls[0].message
    resolved = service.resolve_approval_notification_proposal_token(
        meta=_meta(),
        channel="signal",
        target_timestamp_ms=123,
    )
    assert resolved.ok is True
    assert resolved.payload is not None
    assert resolved.payload.value == "tok-123"
    assert len(cache.values) == 1


def test_health_reports_self_readiness_without_adapter_probe() -> None:
    """Health should report self-readiness without external adapter probing."""
    service, adapter, _cache = _service()
    result = service.health(meta=_meta())

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.service_ready is True
    assert result.payload.value.adapter_ready is True
    assert result.payload.value.detail == "ok"


def test_correlate_approval_response_returns_normalized_payload() -> None:
    """Correlation API should normalize and return approval-correlation payload."""
    service, _adapter, _cache = _service()

    result = service.correlate_approval_response(
        meta=_meta(),
        actor=" operator ",
        channel=" signal ",
        message_text=" approve ",
        reply_to_proposal_token=" tok-1 ",
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.actor == "operator"
    assert result.payload.value.channel == "signal"
    assert result.payload.value.message_text == "approve"
    assert result.payload.value.reply_to_proposal_token == "tok-1"


def test_correlate_approval_response_requires_correlator_or_message() -> None:
    """Correlation API should reject empty payloads without deterministic keys."""
    service, _adapter, _cache = _service()


def test_route_approval_notification_fails_when_correlation_persistence_fails() -> None:
    """Approval notification should fail loudly when correlation persistence fails."""
    service, _adapter, cache = _service()
    cache.fail_set = True

    result = service.route_approval_notification(
        meta=_meta(),
        approval=ApprovalNotificationPayload(
            proposal_token="tok-123",
            capability_id="cap.demo",
            capability_version="1.0.0",
            summary="Need approval",
            actor="operator",
            channel="signal",
            trace_id="trace-1",
            invocation_id="inv-1",
            expires_at=datetime(2026, 2, 25, 12, 0, 0, tzinfo=UTC),
        ),
    )

    assert result.ok is False
    assert result.errors[0].category.value == "dependency"


def test_resolve_approval_notification_token_fails_when_cache_lookup_fails() -> None:
    """Token lookup should surface dependency failure when CAS lookup fails."""
    service, _adapter, cache = _service()
    cache.fail_get = True

    result = service.resolve_approval_notification_proposal_token(
        meta=_meta(),
        channel="signal",
        target_timestamp_ms=123,
    )

    assert result.ok is False
    assert result.errors[0].category.value == "dependency"

    result = service.correlate_approval_response(
        meta=_meta(),
        actor="operator",
        channel="signal",
    )

    assert result.ok is False
    assert result.errors[0].code == "INVALID_ARGUMENT"
