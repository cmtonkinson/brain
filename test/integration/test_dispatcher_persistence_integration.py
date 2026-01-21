"""Integration tests validating dispatcher persistence and audit logging."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import Execution, ExecutionAuditLog, Schedule
from scheduler import data_access
from scheduler.callback_bridge import DispatcherCallbackPayload
from scheduler.execution_dispatcher import (
    ExecutionDispatcher,
    ExecutionInvocationRequest,
    ExecutionInvocationResult,
)
from scheduler.schedule_service_interface import ActorContext
from test.helpers.scheduler_harness import DeterministicClock


class _RecordingInvoker:
    """Invoker stub that records invocation requests and advances the clock."""

    def __init__(self, clock: DeterministicClock) -> None:
        self.calls: list[ExecutionInvocationRequest] = []
        self._clock = clock

    def invoke_execution(self, request: ExecutionInvocationRequest) -> ExecutionInvocationResult:
        """Record the request, advance time, and return success."""
        self.calls.append(request)
        self._clock.advance(seconds=5)
        return ExecutionInvocationResult(
            status="success",
            result_code="ok",
            attention_required=False,
        )


def _seed_schedule(session: Session) -> Schedule:
    """Create a basic interval schedule for dispatcher tests."""
    actor = data_access.ActorContext(
        actor_type="human",
        actor_id="dispatcher-test",
        channel="cli",
        trace_id="trace-seed",
        request_id="req-seed",
    )
    _, schedule = data_access.create_schedule_with_intent(
        session,
        data_access.ScheduleCreateWithIntentInput(
            task_intent=data_access.TaskIntentInput(summary="Dispatcher integration"),
            schedule_type="interval",
            timezone="UTC",
            definition=data_access.ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        actor,
    )
    session.flush()
    return schedule


def test_dispatcher_creates_execution_and_audit_records(sqlite_session_factory) -> None:
    """Ensure dispatcher creates execution records and execution audit entries."""
    with closing(sqlite_session_factory()) as session:
        schedule = _seed_schedule(session)
        session.commit()
        schedule_id = schedule.id
    clock = DeterministicClock(datetime(2025, 5, 12, 7, 0, tzinfo=timezone.utc))
    invoker = _RecordingInvoker(clock)
    dispatcher = ExecutionDispatcher(
        sqlite_session_factory,
        invoker,
        now_provider=clock.provider(),
    )
    scheduled_for = clock.now()

    result = dispatcher.dispatch(
        DispatcherCallbackPayload(
            schedule_id=schedule_id,
            scheduled_for=scheduled_for,
            trace_id="trace-dispatch-audit",
            emitted_at=scheduled_for,
        )
    )

    assert result.status == "dispatched"
    assert result.invocation_request is not None
    assert len(invoker.calls) == 1
    assert invoker.calls[0].execution.schedule_id == schedule.id

    with closing(sqlite_session_factory()) as session:
        execution = session.query(Execution).filter(Execution.id == result.execution_id).one()
        audit_logs = (
            session.query(ExecutionAuditLog)
            .filter(ExecutionAuditLog.execution_id == execution.id)
            .order_by(ExecutionAuditLog.id.asc())
            .all()
        )

    assert len(audit_logs) >= 3
    assert audit_logs[-1].status == "succeeded"
    assert audit_logs[-1].actor_type == "scheduled"
