"""Unit tests for the execution dispatcher."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from models import Execution, ExecutionAuditLog, Schedule
from scheduler import data_access
from scheduler.callback_bridge import DispatcherCallbackPayload
from scheduler.execution_dispatcher import (
    ExecutionDispatchResult,
    ExecutionDispatcher,
    ExecutionDispatcherError,
    ExecutionInvocationRequest,
    ExecutionInvocationResult,
)
from scheduler.retry_policy import RetryPolicy


@dataclass
class _InvocationCall:
    """Capture invocation requests for assertions."""

    request: ExecutionInvocationRequest


class _StubInvoker:
    """Stub invoker that records requests and verifies persistence."""

    def __init__(
        self,
        session_factory,
        *,
        result: ExecutionInvocationResult | None = None,
        error: Exception | None = None,
    ) -> None:
        """Initialize the stub with session access and response behavior."""
        self._session_factory = session_factory
        self._result = result or ExecutionInvocationResult(
            status="success",
            result_code="ok",
            attention_required=False,
        )
        self._error = error
        self.calls: list[_InvocationCall] = []

    def invoke_execution(self, request: ExecutionInvocationRequest) -> ExecutionInvocationResult:
        """Record the invocation and ensure execution is persisted."""
        with closing(self._session_factory()) as session:
            stored = session.query(Execution).filter(Execution.id == request.execution.id).first()
            assert stored is not None
        self.calls.append(_InvocationCall(request=request))
        if self._error is not None:
            raise self._error
        return self._result


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


def _seed_one_time_schedule(session, *, run_at: datetime):
    """Create and return a one-time schedule for tests."""
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
            task_intent=data_access.TaskIntentInput(summary="One-time schedule"),
            schedule_type="one_time",
            timezone="UTC",
            definition=data_access.ScheduleDefinitionInput(run_at=run_at),
            next_run_at=run_at,
        ),
        actor,
        now=run_at - timedelta(hours=1),
    )
    return intent, schedule


def _naive(value: datetime | None) -> datetime | None:
    """Return a naive datetime for comparisons with SQLite storage."""
    if value is None:
        return None
    return value.replace(tzinfo=None)


def test_execution_dispatcher_creates_execution_and_payload(
    sqlite_session_factory,
) -> None:
    """Ensure dispatcher persists execution and builds invocation payload."""
    now = datetime(2025, 2, 1, 9, 0, tzinfo=timezone.utc)
    scheduled_for = datetime(2025, 2, 1, 10, 0, tzinfo=timezone.utc)
    invoker = _StubInvoker(sqlite_session_factory)
    dispatcher = ExecutionDispatcher(
        sqlite_session_factory,
        invoker,
        now_provider=lambda: now,
    )

    with closing(sqlite_session_factory()) as session:
        intent, schedule = _seed_schedule(session)
        schedule_id = schedule.id
        intent_id = intent.id
        session.commit()

    payload = DispatcherCallbackPayload(
        schedule_id=schedule_id,
        scheduled_for=scheduled_for,
        trace_id="callback-123",
        emitted_at=scheduled_for,
    )

    result = dispatcher.dispatch(payload)

    assert isinstance(result, ExecutionDispatchResult)
    assert result.status == "dispatched"
    assert invoker.calls
    request = invoker.calls[0].request
    assert request.execution.schedule_id == schedule_id
    assert request.execution.task_intent_id == intent_id
    assert request.execution.scheduled_for == scheduled_for
    assert request.execution.attempt_number == 1
    assert request.actor_context.actor_type == "scheduled"
    assert request.actor_context.privilege_level == "constrained"
    assert request.actor_context.autonomy_level == "limited"
    assert request.execution_metadata.actual_started_at == now

    with closing(sqlite_session_factory()) as session:
        execution = session.query(Execution).filter(Execution.id == result.execution_id).first()
        assert execution is not None
        assert execution.trace_id == "callback-123"
        assert execution.status == "succeeded"
        schedule = session.query(Schedule).filter(Schedule.id == schedule_id).first()
        assert schedule is not None
        audits = (
            session.query(ExecutionAuditLog)
            .filter(ExecutionAuditLog.execution_id == execution.id)
            .order_by(ExecutionAuditLog.id.asc())
            .all()
        )

    assert [audit.status for audit in audits] == ["queued", "running", "succeeded"]
    assert audits[0].request_id == "callback-123"
    assert audits[0].actor_context is not None
    assert "trigger=scheduler_callback" in audits[0].actor_context
    assert _naive(audits[1].started_at) == _naive(now)
    assert audits[-1].finished_at is not None
    assert _naive(schedule.last_run_at) == _naive(now)
    assert str(schedule.last_run_status) == "succeeded"
    assert schedule.last_execution_id == execution.id
    assert schedule.failure_count == 0
    assert _naive(schedule.next_run_at) == _naive(scheduled_for + timedelta(days=1))


def test_execution_dispatcher_rejects_inactive_schedule(
    sqlite_session_factory,
) -> None:
    """Ensure dispatcher rejects callbacks for non-active schedules."""
    invoker = _StubInvoker(sqlite_session_factory)
    dispatcher = ExecutionDispatcher(sqlite_session_factory, invoker)

    with closing(sqlite_session_factory()) as session:
        _, schedule = _seed_schedule(session)
        schedule.state = "paused"
        schedule_id = schedule.id
        session.commit()

    payload = DispatcherCallbackPayload(
        schedule_id=schedule_id,
        scheduled_for=datetime(2025, 2, 2, 10, 0, tzinfo=timezone.utc),
        trace_id="callback-paused",
        emitted_at=datetime(2025, 2, 2, 10, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(ExecutionDispatcherError) as excinfo:
        dispatcher.dispatch(payload)

    assert excinfo.value.code == "schedule_inactive"


def test_execution_dispatcher_idempotent_audit_on_replay(
    sqlite_session_factory,
) -> None:
    """Ensure replayed callbacks do not duplicate execution audit logs."""
    scheduled_for = datetime(2025, 2, 3, 10, 0, tzinfo=timezone.utc)
    invoker = _StubInvoker(sqlite_session_factory)
    dispatcher = ExecutionDispatcher(sqlite_session_factory, invoker)

    with closing(sqlite_session_factory()) as session:
        _, schedule = _seed_schedule(session)
        schedule_id = schedule.id
        session.commit()

    payload = DispatcherCallbackPayload(
        schedule_id=schedule_id,
        scheduled_for=scheduled_for,
        trace_id="callback-dup",
        emitted_at=scheduled_for,
    )

    first = dispatcher.dispatch(payload)
    second = dispatcher.dispatch(payload)

    assert first.status == "dispatched"
    assert second.status == "duplicate"
    assert len(invoker.calls) == 1

    with closing(sqlite_session_factory()) as session:
        audits = (
            session.query(ExecutionAuditLog)
            .filter(ExecutionAuditLog.execution_id == first.execution_id)
            .order_by(ExecutionAuditLog.id.asc())
            .all()
        )

    assert len(audits) == 3


def test_execution_dispatcher_records_exception_failure_audit(
    sqlite_session_factory,
) -> None:
    """Ensure dispatcher logs retry scheduling when invoker raises exceptions."""
    scheduled_for = datetime(2025, 2, 4, 10, 0, tzinfo=timezone.utc)
    now = datetime(2025, 2, 4, 9, 55, tzinfo=timezone.utc)
    invoker = _StubInvoker(sqlite_session_factory, error=RuntimeError("boom"))
    retry_policy = RetryPolicy(
        max_attempts=2,
        backoff_strategy="fixed",
        backoff_base_seconds=300,
    )
    dispatcher = ExecutionDispatcher(
        sqlite_session_factory,
        invoker,
        now_provider=lambda: now,
        retry_policy=retry_policy,
    )

    with closing(sqlite_session_factory()) as session:
        _, schedule = _seed_schedule(session)
        schedule_id = schedule.id
        session.commit()

    payload = DispatcherCallbackPayload(
        schedule_id=schedule_id,
        scheduled_for=scheduled_for,
        trace_id="callback-exc",
        emitted_at=scheduled_for,
    )

    with pytest.raises(RuntimeError):
        dispatcher.dispatch(payload)

    with closing(sqlite_session_factory()) as session:
        execution = (
            session.query(Execution)
            .filter(Execution.schedule_id == schedule_id)
            .order_by(Execution.id.desc())
            .first()
        )
        assert execution is not None
        audits = (
            session.query(ExecutionAuditLog)
            .filter(ExecutionAuditLog.execution_id == execution.id)
            .order_by(ExecutionAuditLog.id.asc())
            .all()
        )
        schedule = session.query(Schedule).filter(Schedule.id == schedule_id).first()
        assert schedule is not None

    assert [audit.status for audit in audits] == ["queued", "running", "retry_scheduled"]
    assert audits[-1].last_error_code == "invoker_exception"
    assert audits[-1].last_error_message == "boom"
    assert _naive(audits[-1].next_retry_at) == _naive(now + timedelta(minutes=5))
    assert schedule.failure_count == 1
    assert str(schedule.last_run_status) == "retry_scheduled"


def test_execution_dispatcher_records_deferred_retry_audit(
    sqlite_session_factory,
) -> None:
    """Ensure deferred executions write retry audit metadata."""
    scheduled_for = datetime(2025, 2, 5, 10, 0, tzinfo=timezone.utc)
    now = datetime(2025, 2, 5, 9, 55, tzinfo=timezone.utc)
    invoker = _StubInvoker(
        sqlite_session_factory,
        result=ExecutionInvocationResult(
            status="deferred",
            result_code="defer",
            attention_required=False,
        ),
    )
    retry_policy = RetryPolicy(
        max_attempts=3,
        backoff_strategy="fixed",
        backoff_base_seconds=300,
    )
    dispatcher = ExecutionDispatcher(
        sqlite_session_factory,
        invoker,
        now_provider=lambda: now,
        retry_policy=retry_policy,
    )

    with closing(sqlite_session_factory()) as session:
        _, schedule = _seed_schedule(session)
        schedule_id = schedule.id
        session.commit()

    payload = DispatcherCallbackPayload(
        schedule_id=schedule_id,
        scheduled_for=scheduled_for,
        trace_id="callback-defer",
        emitted_at=scheduled_for,
    )

    dispatcher.dispatch(payload)

    with closing(sqlite_session_factory()) as session:
        execution = (
            session.query(Execution)
            .filter(Execution.schedule_id == schedule_id)
            .order_by(Execution.id.desc())
            .first()
        )
        assert execution is not None
        audits = (
            session.query(ExecutionAuditLog)
            .filter(ExecutionAuditLog.execution_id == execution.id)
            .order_by(ExecutionAuditLog.id.asc())
            .all()
        )
        schedule = session.query(Schedule).filter(Schedule.id == schedule_id).first()
        assert schedule is not None

    assert [audit.status for audit in audits] == ["queued", "running", "retry_scheduled"]
    assert _naive(audits[-1].next_retry_at) == _naive(now + timedelta(minutes=5))
    assert str(schedule.last_run_status) == "retry_scheduled"
    assert schedule.failure_count == 1


def test_execution_dispatcher_updates_one_time_schedule_completion(
    sqlite_session_factory,
) -> None:
    """Ensure one-time schedules are marked complete after success."""
    now = datetime(2025, 2, 6, 9, 0, tzinfo=timezone.utc)
    scheduled_for = datetime(2025, 2, 6, 10, 0, tzinfo=timezone.utc)
    invoker = _StubInvoker(
        sqlite_session_factory,
        result=ExecutionInvocationResult(
            status="success",
            result_code="ok",
            attention_required=False,
        ),
    )
    dispatcher = ExecutionDispatcher(
        sqlite_session_factory,
        invoker,
        now_provider=lambda: now,
    )

    with closing(sqlite_session_factory()) as session:
        _, schedule = _seed_one_time_schedule(session, run_at=scheduled_for)
        schedule_id = schedule.id
        session.commit()

    payload = DispatcherCallbackPayload(
        schedule_id=schedule_id,
        scheduled_for=scheduled_for,
        trace_id="callback-one-time",
        emitted_at=scheduled_for,
    )

    dispatcher.dispatch(payload)

    with closing(sqlite_session_factory()) as session:
        schedule = session.query(Schedule).filter(Schedule.id == schedule_id).first()
        assert schedule is not None

    assert str(schedule.state) == "completed"
    assert schedule.next_run_at is None
    assert _naive(schedule.last_run_at) == _naive(now)
