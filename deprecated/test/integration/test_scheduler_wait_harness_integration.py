"""Integration test for scheduler test harness utilities."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

from scheduler import data_access
from scheduler.callback_bridge import DispatcherCallbackPayload
from scheduler.execution_dispatcher import (
    ExecutionDispatcher,
    ExecutionInvocationRequest,
    ExecutionInvocationResult,
)
from test.helpers.scheduler_harness import DeterministicClock, wait_for_execution_status


class _SuccessInvoker:
    """Invoker that returns a successful execution result."""

    def __init__(self) -> None:
        """Initialize the invoker with an empty call log."""
        self.calls: list[ExecutionInvocationRequest] = []

    def invoke_execution(self, request: ExecutionInvocationRequest) -> ExecutionInvocationResult:
        """Record the request and return a success response."""
        self.calls.append(request)
        return ExecutionInvocationResult(
            status="success",
            result_code="ok",
            attention_required=False,
            message="Execution succeeded.",
        )


def _seed_schedule(session) -> int:
    """Create and return a schedule id for harness tests."""
    _, schedule = data_access.create_schedule_with_intent(
        session,
        data_access.ScheduleCreateWithIntentInput(
            task_intent=data_access.TaskIntentInput(summary="Harness integration"),
            schedule_type="interval",
            timezone="UTC",
            definition=data_access.ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        data_access.ActorContext(
            actor_type="human",
            actor_id="tester",
            channel="cli",
            trace_id="trace-harness",
            request_id="req-harness",
        ),
    )
    session.flush()
    return schedule.id


def test_wait_for_execution_completion_with_deterministic_clock(sqlite_session_factory) -> None:
    """Use harness helpers to wait for a completed execution deterministically."""
    session_factory = sqlite_session_factory
    with closing(session_factory()) as session:
        schedule_id = _seed_schedule(session)
        session.commit()

    clock = DeterministicClock(datetime(2025, 3, 1, 12, 0, tzinfo=timezone.utc))
    invoker = _SuccessInvoker()
    dispatcher = ExecutionDispatcher(
        session_factory,
        invoker,
        now_provider=clock.provider(),
    )
    scheduled_for = clock.now()

    result = dispatcher.dispatch(
        DispatcherCallbackPayload(
            schedule_id=schedule_id,
            scheduled_for=scheduled_for,
            trace_id="trace-harness-1",
            emitted_at=scheduled_for,
        )
    )

    execution = wait_for_execution_status(
        session_factory,
        execution_id=result.execution_id,
        expected_statuses=("succeeded",),
        timeout_seconds=0.2,
        poll_interval_seconds=0.01,
    )

    assert len(invoker.calls) == 1
    assert execution.status == "succeeded"
    assert execution.started_at == scheduled_for
    assert execution.finished_at == scheduled_for
