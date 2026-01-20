"""Unit tests for scheduler callback bridge behavior."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone

from scheduler import data_access
from scheduler.adapters.celery_callback_bridge import (
    CeleryCallbackRequest,
    translate_celery_callback,
)
from scheduler.callback_bridge import CallbackBridge, DispatcherCallbackPayload


@dataclass
class _DispatchCall:
    """Captured dispatcher call payload for tests."""

    payload: DispatcherCallbackPayload


class _StubDispatcher:
    """Dispatcher stub capturing callback payloads."""

    def __init__(self) -> None:
        """Initialize the stub call list."""
        self.calls: list[_DispatchCall] = []

    def dispatch(self, payload: DispatcherCallbackPayload) -> None:
        """Capture dispatcher invocations."""
        self.calls.append(_DispatchCall(payload=payload))


def _seed_schedule(session):
    """Create and return a task intent + schedule pair for tests."""
    actor = data_access.ActorContext(
        actor_type="human",
        actor_id="tester",
        channel="cli",
        trace_id="trace-seed",
        request_id="req-seed",
    )
    intent, schedule = data_access.create_schedule_with_intent(
        session,
        data_access.ScheduleCreateWithIntentInput(
            task_intent=data_access.TaskIntentInput(summary="Test schedule"),
            schedule_type="interval",
            timezone="UTC",
            definition=data_access.ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        actor,
    )
    return intent, schedule


def _execution_actor(correlation_id: str) -> data_access.ExecutionActorContext:
    """Return an execution actor context for scheduler callbacks."""
    return data_access.ExecutionActorContext(
        actor_type="scheduled",
        actor_id=None,
        channel="scheduled",
        trace_id="trace-callback",
        request_id="req-callback",
        correlation_id=correlation_id,
    )


def test_translate_celery_callback_uses_emitted_at_when_missing() -> None:
    """Ensure translation falls back to emitted_at when scheduled_for is None."""
    emitted_at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    request = CeleryCallbackRequest(
        schedule_id=11,
        scheduled_for=None,
        correlation_id="cb-11",
        emitted_at=emitted_at,
        provider_attempt=1,
        provider_task_id="celery-task-11",
    )

    payload = translate_celery_callback(request)

    assert payload.schedule_id == 11
    assert payload.scheduled_for == emitted_at
    assert payload.correlation_id == "cb-11"
    assert payload.emitted_at == emitted_at


def test_callback_bridge_skips_duplicate_callbacks(
    sqlite_session_factory,
) -> None:
    """Ensure callback bridge does not dispatch duplicates."""
    dispatcher = _StubDispatcher()
    bridge = CallbackBridge(sqlite_session_factory, dispatcher)
    scheduled_for = datetime(2025, 1, 2, 9, 0, tzinfo=timezone.utc)

    with closing(sqlite_session_factory()) as session:
        intent, schedule = _seed_schedule(session)
        schedule_id = schedule.id
        data_access.create_execution(
            session,
            data_access.ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule_id,
                scheduled_for=scheduled_for,
            ),
            _execution_actor("cb-duplicate"),
        )
        session.commit()

    payload = DispatcherCallbackPayload(
        schedule_id=schedule_id,
        scheduled_for=scheduled_for,
        correlation_id="cb-duplicate",
        emitted_at=scheduled_for,
    )

    result = bridge.handle_callback(payload)

    assert result.status == "duplicate"
    assert dispatcher.calls == []


def test_callback_bridge_dispatches_new_callbacks(
    sqlite_session_factory,
) -> None:
    """Ensure callback bridge dispatches when no duplicate exists."""
    dispatcher = _StubDispatcher()
    bridge = CallbackBridge(sqlite_session_factory, dispatcher)
    scheduled_for = datetime(2025, 1, 3, 10, 0, tzinfo=timezone.utc)

    with closing(sqlite_session_factory()) as session:
        _, schedule = _seed_schedule(session)
        schedule_id = schedule.id
        session.commit()

    payload = DispatcherCallbackPayload(
        schedule_id=schedule_id,
        scheduled_for=scheduled_for,
        correlation_id="cb-new",
        emitted_at=scheduled_for,
    )

    result = bridge.handle_callback(payload)

    assert result.status == "accepted"
    assert dispatcher.calls
