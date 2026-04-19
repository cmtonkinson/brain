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
    SignalCallbackRegistrationResult,
    SignalInboundCallback,
)
from services.action.attention_router.config import AttentionRouterServiceSettings
from services.action.attention_router.domain import ApprovalNotificationPayload
from services.action.attention_router.implementation import (
    DefaultAttentionRouterService,
)
from services.state.cache_authority.domain import CacheEntry
from services.state.cache_authority.service import CacheAuthorityService
from services.state.memory_authority.domain import (
    SessionRecord,
    TurnDirection,
    TurnRecord,
)
from services.state.memory_authority.service import (
    ConversationalMemoryContext,
    MemoryAuthorityService,
)


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

    def register_callback(
        self,
        *,
        callback: SignalInboundCallback,
    ) -> SignalCallbackRegistrationResult:
        del callback
        return SignalCallbackRegistrationResult(registered=True, detail="ok")

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


class _FakeMemoryAuthorityService(MemoryAuthorityService):
    """In-memory MAS fake for conversational outbound persistence tests."""

    def __init__(self) -> None:
        self.candidates: list[dict[str, object]] = []
        self.deliveries: list[dict[str, object]] = []

    def record_inbound_turn(
        self, *, meta, session_id: str, message: str, instruction=None
    ):
        raise NotImplementedError

    def assemble_snapshot(self, *, meta, session_id: str, exclude_latest: bool = True):
        raise NotImplementedError

    def record_outbound_candidate(
        self,
        *,
        meta,
        session_id: str,
        content: str,
        model: str,
        provider: str,
        token_count: int,
        reasoning_level: str,
    ):
        del meta
        self.candidates.append(
            {
                "session_id": session_id,
                "content": content,
                "model": model,
                "provider": provider,
                "token_count": token_count,
                "reasoning_level": reasoning_level,
            }
        )
        return success(
            meta=_meta(),
            payload=TurnRecord(
                id="turn-1",
                session_id=session_id,
                direction=TurnDirection.OUTBOUND,
                content=content,
                role="assistant",
                model=model,
                provider=provider,
                token_count=token_count,
                reasoning_level=reasoning_level,
                trace_id="trace-1",
                principal="operator",
                created_at=datetime.now(UTC),
            ),
        )

    def record_outbound_delivery(
        self, *, meta, session_id: str, turn_id: str, delivered: bool
    ):
        del meta
        self.deliveries.append(
            {
                "session_id": session_id,
                "turn_id": turn_id,
                "delivered": delivered,
            }
        )
        return success(meta=_meta(), payload=delivered)

    def assemble_context(self, *, meta, session_id: str, message: str):
        raise NotImplementedError

    def record_response(
        self,
        *,
        meta,
        session_id: str,
        content: str,
        model: str,
        provider: str,
        token_count: int,
        reasoning_level: str,
    ):
        raise NotImplementedError

    def update_focus(self, *, meta, session_id: str, content: str):
        raise NotImplementedError

    def clear_session(self, *, meta, session_id: str):
        raise NotImplementedError

    def create_session(self, *, meta):
        return success(
            meta=_meta(),
            payload=SessionRecord(
                id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                focus=None,
                focus_token_count=None,
                dialogue_summary=None,
                dialogue_summary_token_count=None,
                dialogue_start_turn_id=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
        )

    def get_latest_or_create_session(self, *, meta):
        raise NotImplementedError

    def get_session(self, *, meta, session_id: str):
        raise NotImplementedError

    def health(self, *, meta):
        raise NotImplementedError


def _meta():
    """Build valid envelope metadata for Attention Router tests."""
    return new_meta(
        kind=EnvelopeKind.EVENT, source="attention-router", principal="operator"
    )


def _service() -> tuple[
    DefaultAttentionRouterService,
    _FakeSignalAdapter,
    _FakeCacheAuthorityService,
    _FakeMemoryAuthorityService,
]:
    """Build Attention Router with in-memory dependencies for tests."""
    adapter = _FakeSignalAdapter()
    cache = _FakeCacheAuthorityService()
    memory = _FakeMemoryAuthorityService()
    service = DefaultAttentionRouterService(
        settings=AttentionRouterServiceSettings(
            default_channel="signal",
            conversational_channels=("signal",),
            dedupe_window_seconds=120,
            rate_limit_window_seconds=60,
            rate_limit_max_per_window=2,
            batch_summary_max_items=2,
        ),
        signal_adapter=adapter,
        operator_signal_contact_e164="+12025550100",
        signal_receive_e164="+12025550101",
        console_response_queue_name="console_outbound",
        cache_authority_service=cache,
        memory_authority_service=memory,
    )
    return service, adapter, cache, memory


def test_route_notification_delivers_signal_message() -> None:
    """Signal notification should be delivered with resolved defaults."""
    service, adapter, _cache, memory = _service()

    result = service.route_notification(meta=_meta(), message="hello")

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.decision == "sent"
    assert result.payload.value.delivered is True
    assert len(adapter.send_calls) == 1
    assert adapter.send_calls[0].recipient_e164 == "+12025550100"
    assert memory.candidates == []
    assert memory.deliveries == []


def test_route_notification_suppresses_recent_dedupe_key() -> None:
    """Same dedupe key within configured window should be suppressed."""
    service, adapter, _cache, _memory = _service()

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
    service, adapter, _cache, memory = _service()

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
    assert memory.candidates == []


def test_flush_batch_delivers_consolidated_summary() -> None:
    """Flushing a pending batch should deliver one summary notification."""
    service, adapter, _cache, memory = _service()
    service.route_notification(meta=_meta(), message="first", batch_key="digest")
    service.route_notification(meta=_meta(), message="second", batch_key="digest")
    service.route_notification(meta=_meta(), message="third", batch_key="digest")

    flushed = service.flush_batch(meta=_meta(), batch_key="digest")

    assert flushed.ok is True
    assert flushed.payload is not None
    assert flushed.payload.value.decision == "sent"
    assert len(adapter.send_calls) == 1
    assert "... and 1 more" in adapter.send_calls[0].message
    assert memory.candidates == []


def test_route_notification_persists_sent_conversational_outbound_to_mas() -> None:
    """Sent notifications on conversational channels should be recorded in MAS."""
    service, adapter, _cache, memory = _service()

    result = service.route_notification(
        meta=_meta(),
        message="hello",
        conversational_memory=ConversationalMemoryContext(
            session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            model="claude-sonnet",
            provider="anthropic",
            token_count=2,
            reasoning_level="standard",
        ),
    )

    assert result.ok is True
    assert len(adapter.send_calls) == 1
    assert memory.candidates == [
        {
            "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "content": "hello",
            "model": "claude-sonnet",
            "provider": "anthropic",
            "token_count": 2,
            "reasoning_level": "standard",
        }
    ]
    assert memory.deliveries == [
        {
            "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "turn_id": "turn-1",
            "delivered": True,
        }
    ]


def test_route_notification_skips_mas_for_non_conversational_channel() -> None:
    """Sent notifications on non-conversational channels should not hit MAS."""
    service, adapter, _cache, memory = _service()
    service._settings = service._settings.model_copy(  # type: ignore[misc]
        update={"conversational_channels": ()}
    )

    result = service.route_notification(
        meta=_meta(),
        message="hello",
        conversational_memory=ConversationalMemoryContext(
            session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            model="claude-sonnet",
            provider="anthropic",
            token_count=2,
            reasoning_level="standard",
        ),
    )

    assert result.ok is True
    assert len(adapter.send_calls) == 1
    assert memory.candidates == []
    assert memory.deliveries == []


def test_flush_batch_persists_when_sent_with_stable_conversational_context() -> None:
    """Flushed conversational batches should write one emitted outbound to MAS."""
    service, adapter, _cache, memory = _service()
    context = ConversationalMemoryContext(
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        model="claude-sonnet",
        provider="anthropic",
        token_count=12,
        reasoning_level="standard",
    )
    service.route_notification(
        meta=_meta(),
        message="first",
        batch_key="digest",
        conversational_memory=context,
    )
    service.route_notification(
        meta=_meta(),
        message="second",
        batch_key="digest",
        conversational_memory=context,
    )

    result = service.flush_batch(meta=_meta(), batch_key="digest")

    assert result.ok is True
    assert len(adapter.send_calls) == 1
    assert len(memory.candidates) == 1
    assert memory.candidates[0]["session_id"] == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert memory.candidates[0]["content"] == adapter.send_calls[0].message
    assert memory.deliveries == [
        {
            "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "turn_id": "turn-1",
            "delivered": True,
        }
    ]


def test_route_notification_propagates_signal_dependency_errors() -> None:
    """Signal dependency errors should map to dependency envelope failures."""
    service, adapter, _cache, _memory = _service()
    adapter.raise_send = SignalAdapterDependencyError("signal unavailable")

    result = service.route_notification(meta=_meta(), message="hello")

    assert result.ok is False
    assert result.errors[0].category.value == "dependency"


def test_route_notification_suppresses_when_rate_limited() -> None:
    """Exceeding channel/recipient send window should suppress delivery."""
    service, adapter, _cache, _memory = _service()

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
    service, adapter, cache, _memory = _service()

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
    service, adapter, _cache, _memory = _service()
    result = service.health(meta=_meta())

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.service_ready is True
    assert result.payload.value.adapter_ready is True
    assert result.payload.value.detail == "ok"


def test_correlate_approval_response_returns_normalized_payload() -> None:
    """Correlation API should normalize and return approval-correlation payload."""
    service, _adapter, _cache, _memory = _service()

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
    service, _adapter, _cache, _memory = _service()


def test_route_approval_notification_fails_when_correlation_persistence_fails() -> None:
    """Approval notification should fail loudly when correlation persistence fails."""
    service, _adapter, cache, _memory = _service()
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
    service, _adapter, cache, _memory = _service()
    cache.fail_get = True

    result = service.resolve_approval_notification_proposal_token(
        meta=_meta(),
        channel="signal",
        target_timestamp_ms=123,
    )

    assert result.ok is False
    assert result.errors[0].category.value == "dependency"


def test_resolve_approval_notification_token_returns_none_when_cache_value_missing() -> (
    None
):
    """Token lookup should treat empty CAS payload values as a cache miss."""
    service, _adapter, cache, _memory = _service()
    cache.values[("attention-router", "approval-timestamp:signal:123")] = None

    result = service.resolve_approval_notification_proposal_token(
        meta=_meta(),
        channel="signal",
        target_timestamp_ms=123,
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value is None

    result = service.correlate_approval_response(
        meta=_meta(),
        actor="operator",
        channel="signal",
    )

    assert result.ok is False
    assert result.errors[0].code == "INVALID_ARGUMENT"
