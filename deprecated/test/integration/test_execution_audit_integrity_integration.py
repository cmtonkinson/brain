"""Integration tests for execution audit integrity requirements."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import ExecutionAuditLog
from scheduler import data_access
from scheduler.callback_bridge import DispatcherCallbackPayload
from scheduler.execution_dispatcher import (
    ExecutionDispatcher,
    ExecutionInvocationRequest,
    ExecutionInvocationResult,
)
from test.helpers.scheduler_harness import DeterministicClock


def _seed_schedule(session: Session) -> data_access.Schedule:
    """Persist a simple interval schedule used across execution tests."""
    actor = data_access.ActorContext(
        actor_type="human",
        actor_id="audit-test",
        channel="cli",
        trace_id="trace-audit-seed",
        request_id="req-audit-seed",
    )
    _, schedule = data_access.create_schedule_with_intent(
        session,
        data_access.ScheduleCreateWithIntentInput(
            task_intent=data_access.TaskIntentInput(summary="Execution audit"),
            schedule_type="interval",
            timezone="UTC",
            definition=data_access.ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        actor,
    )
    session.flush()
    return schedule


class _AdvancingInvoker:
    """Invoker that advances the clock when processing executions."""

    def __init__(self, clock: DeterministicClock) -> None:
        self.calls: list[ExecutionInvocationRequest] = []
        self._clock = clock

    def invoke_execution(self, request: ExecutionInvocationRequest) -> ExecutionInvocationResult:
        """Record the invocation, advance time, and return success."""
        self.calls.append(request)
        self._clock.advance(seconds=10)
        return ExecutionInvocationResult(
            status="success",
            result_code="ok",
            attention_required=False,
        )


def test_execution_audit_records_are_linked_and_idempotent(
    sqlite_session_factory,
) -> None:
    """Verify execution audit logs carry actor context, timestamps, and avoid duplicates."""
    with closing(sqlite_session_factory()) as session:
        schedule = _seed_schedule(session)
        session.commit()
        schedule_id = schedule.id

    clock = DeterministicClock(datetime(2025, 8, 6, 14, 0, tzinfo=timezone.utc))
    invoker = _AdvancingInvoker(clock)
    dispatcher = ExecutionDispatcher(
        sqlite_session_factory,
        invoker,
        now_provider=clock.provider(),
    )
    payload = DispatcherCallbackPayload(
        schedule_id=schedule_id,
        scheduled_for=clock.now(),
        trace_id="trace-exec-audit",
        emitted_at=clock.now(),
    )

    result = dispatcher.dispatch(payload)
    assert result.status == "dispatched"

    final_time = clock.now()
    with closing(sqlite_session_factory()) as session:
        logs = (
            session.query(ExecutionAuditLog)
            .filter(ExecutionAuditLog.execution_id == result.execution_id)
            .order_by(ExecutionAuditLog.id.asc())
            .all()
        )
    assert logs
    assert logs[-1].trace_id == "trace-exec-audit"
    assert "trigger=scheduler_callback" in (logs[-1].actor_context or "")
    occurred = logs[-1].occurred_at
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    assert occurred == final_time

    prior_count = len(logs)
    duplicate_result = dispatcher.dispatch(payload)
    assert duplicate_result.status == "duplicate"
    assert duplicate_result.execution_id == result.execution_id

    with closing(sqlite_session_factory()) as session:
        logs_after = (
            session.query(ExecutionAuditLog)
            .filter(ExecutionAuditLog.execution_id == result.execution_id)
            .all()
        )
    assert len(logs_after) == prior_count
