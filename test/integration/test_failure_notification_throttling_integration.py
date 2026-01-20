"""Integration tests for scheduled failure notification routing."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

from attention.router import AttentionRouter
from models import NotificationHistoryEntry
from scheduler import data_access
from scheduler.callback_bridge import DispatcherCallbackPayload
from scheduler.execution_dispatcher import (
    ExecutionDispatcher,
    ExecutionInvocationRequest,
    ExecutionInvocationResult,
)
from scheduler.failure_notifications import FailureNotificationConfig, FailureNotificationService


class _FakeSignalClient:
    """Stub Signal client that records sends."""

    def __init__(self) -> None:
        """Initialize the client with an empty send log."""
        self.sent: list[str] = []

    async def send_message(
        self,
        from_number: str,
        to_number: str,
        message: str,
        *,
        source_component: str = "unknown",
    ) -> bool:
        """Record the outgoing message and return success."""
        self.sent.append(message)
        return True


class _FailureInvoker:
    """Invoker that always returns a failure result."""

    def __init__(self) -> None:
        """Initialize the invoker."""
        self.calls: list[ExecutionInvocationRequest] = []

    def invoke_execution(self, request: ExecutionInvocationRequest) -> ExecutionInvocationResult:
        """Return a failed invocation result."""
        self.calls.append(request)
        return ExecutionInvocationResult(
            status="failure",
            result_code="execution_failed",
            attention_required=False,
            message="Execution failed.",
        )


def _seed_schedule(session) -> int:
    """Create and return a schedule ID for integration tests."""
    actor = data_access.ActorContext(
        actor_type="human",
        actor_id="tester",
        channel="cli",
        trace_id="trace-seed",
        request_id="req-seed",
    )
    _, schedule = data_access.create_schedule_with_intent(
        session,
        data_access.ScheduleCreateWithIntentInput(
            task_intent=data_access.TaskIntentInput(summary="Failure notification task"),
            schedule_type="interval",
            timezone="UTC",
            definition=data_access.ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        actor,
    )
    return schedule.id


def test_failure_notification_routes_after_threshold(sqlite_session_factory) -> None:
    """Ensure repeated failures trigger an attention-routed notification."""
    scheduled_for = datetime(2025, 2, 7, 10, 0, tzinfo=timezone.utc)
    with closing(sqlite_session_factory()) as session:
        schedule_id = _seed_schedule(session)
        session.commit()

    router = AttentionRouter(
        signal_client=_FakeSignalClient(),
        session_factory=sqlite_session_factory,
    )
    notifier = FailureNotificationService(
        sqlite_session_factory,
        router,
        config=FailureNotificationConfig(threshold=2, throttle_window_seconds=0),
    )
    dispatcher = ExecutionDispatcher(
        sqlite_session_factory,
        _FailureInvoker(),
        failure_notifier=notifier,
    )

    dispatcher.dispatch(
        DispatcherCallbackPayload(
            schedule_id=schedule_id,
            scheduled_for=scheduled_for,
            trace_id="failure-1",
            emitted_at=scheduled_for,
        )
    )
    assert router.routed_sources() == []

    dispatcher.dispatch(
        DispatcherCallbackPayload(
            schedule_id=schedule_id,
            scheduled_for=scheduled_for,
            trace_id="failure-2",
            emitted_at=scheduled_for,
        )
    )

    assert router.routed_sources() == ["scheduler_dispatcher"]

    with closing(sqlite_session_factory()) as session:
        history = (
            session.query(NotificationHistoryEntry)
            .filter(NotificationHistoryEntry.signal_reference == f"schedule.failure:{schedule_id}")
            .all()
        )
        assert len(history) == 1
