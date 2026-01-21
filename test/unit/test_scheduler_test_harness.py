"""Unit tests for scheduler test harness helpers."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

import pytest

from scheduler import data_access
from test.helpers.scheduler_harness import DeterministicClock, wait_for_execution_status


def _schedule_actor() -> data_access.ActorContext:
    """Return a default actor context for schedule creation."""
    return data_access.ActorContext(
        actor_type="human",
        actor_id="tester",
        channel="cli",
        trace_id="trace-schedule",
        request_id="req-schedule",
    )


def _execution_actor() -> data_access.ExecutionActorContext:
    """Return a default actor context for execution records."""
    return data_access.ExecutionActorContext(
        actor_type="scheduled",
        actor_id=None,
        channel="scheduler",
        trace_id="trace-execution",
        request_id="req-execution",
        actor_context="scheduled:test",
    )


def _seed_schedule(session) -> data_access.Schedule:
    """Create a schedule for harness tests."""
    _, schedule = data_access.create_schedule_with_intent(
        session,
        data_access.ScheduleCreateWithIntentInput(
            task_intent=data_access.TaskIntentInput(summary="Harness test"),
            schedule_type="interval",
            timezone="UTC",
            definition=data_access.ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        _schedule_actor(),
    )
    session.flush()
    return schedule


def test_deterministic_clock_advances_and_sets() -> None:
    """Ensure the deterministic clock normalizes and advances time."""
    clock = DeterministicClock(datetime(2025, 1, 1, 12, 0, 0))

    assert clock.now().tzinfo == timezone.utc
    assert clock.advance(hours=1, minutes=15) == datetime(2025, 1, 1, 13, 15, tzinfo=timezone.utc)

    target = datetime(2025, 1, 2, 9, 30, tzinfo=timezone.utc)
    assert clock.set(target) == target


def test_wait_for_execution_status_returns_execution(sqlite_session_factory) -> None:
    """Return the execution once it reaches the expected status."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        schedule = _seed_schedule(session)
        execution = data_access.create_execution(
            session,
            data_access.ExecutionCreateInput(
                task_intent_id=schedule.task_intent_id,
                schedule_id=schedule.id,
                scheduled_for=now,
                status="succeeded",
                attempt_count=1,
                max_attempts=1,
            ),
            _execution_actor(),
            now=now,
        )
        session.commit()
        execution_id = execution.id

    found = wait_for_execution_status(
        session_factory,
        execution_id=execution_id,
        expected_statuses=("succeeded",),
        timeout_seconds=0.2,
        poll_interval_seconds=0.01,
    )

    assert found.id == execution_id
    assert str(found.status) == "succeeded"


def test_wait_for_execution_status_times_out(sqlite_session_factory) -> None:
    """Raise a timeout when no execution reaches the expected status."""
    session_factory = sqlite_session_factory
    with closing(session_factory()) as session:
        schedule = _seed_schedule(session)
        schedule_id = schedule.id
        session.commit()

    with pytest.raises(TimeoutError):
        wait_for_execution_status(
            session_factory,
            schedule_id=schedule_id,
            expected_statuses=("succeeded",),
            timeout_seconds=0.05,
            poll_interval_seconds=0.01,
        )
