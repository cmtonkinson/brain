"""Unit tests for the schedule command service handlers."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from models import Execution, Schedule, TaskIntent
from scheduler.schedule_service import ScheduleCommandServiceImpl
from scheduler.schedule_service_interface import (
    ActorContext,
    ScheduleConflictError,
    ScheduleCreateRequest,
    ScheduleNotFoundError,
    SchedulePauseRequest,
    ScheduleRunNowRequest,
    ScheduleUpdateRequest,
    ScheduleDefinitionInput,
    TaskIntentInput,
)


def _actor_context() -> ActorContext:
    """Return a default actor context for schedule mutations."""
    return ActorContext(
        actor_type="human",
        actor_id="user-1",
        channel="signal",
        trace_id="trace-xyz",
        request_id="req-123",
        reason="unit-test",
    )


def _schedule(now: datetime) -> Schedule:
    """Return a schedule model populated for unit tests."""
    return Schedule(
        id=10,
        task_intent_id=99,
        schedule_type="interval",
        state="active",
        timezone="UTC",
        next_run_at=None,
        last_run_at=None,
        last_run_status=None,
        failure_count=0,
        created_by_actor_type="human",
        created_by_actor_id="user-1",
        created_at=now,
        updated_at=now,
        interval_count=1,
        interval_unit="day",
    )


def _task_intent(now: datetime) -> TaskIntent:
    """Return a task intent model populated for unit tests."""
    return TaskIntent(
        id=99,
        summary="Daily check-in",
        details="Check the status report.",
        creator_actor_type="human",
        creator_actor_id="user-1",
        creator_channel="signal",
        origin_reference="signal:thread-1",
        created_at=now,
        updated_at=now,
        superseded_by_intent_id=None,
    )


def test_create_schedule_routes_to_data_access() -> None:
    """Ensure create schedule handler routes through data access."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    service = ScheduleCommandServiceImpl(session_factory, now_provider=lambda: now)
    actor = _actor_context()
    intent = _task_intent(now)
    schedule = _schedule(now)

    request = ScheduleCreateRequest(
        task_intent=TaskIntentInput(summary="Daily check-in", details="Check the status report."),
        schedule_type="interval",
        timezone="UTC",
        definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
    )

    with (
        patch(
            "scheduler.schedule_service.data_access.create_schedule_with_intent",
            return_value=(intent, schedule),
        ) as create_mock,
        patch(
            "scheduler.schedule_service._fetch_latest_schedule_audit_id",
            return_value=42,
        ),
    ):
        result = service.create_schedule(request, actor)

    assert result.audit_log_id == 42
    assert result.schedule.id == schedule.id
    create_mock.assert_called_once()
    session.commit.assert_called_once()


def test_update_schedule_maps_not_found() -> None:
    """Ensure not-found errors are mapped on update."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    service = ScheduleCommandServiceImpl(session_factory, now_provider=lambda: now)
    actor = _actor_context()

    request = ScheduleUpdateRequest(schedule_id=404, timezone="UTC")

    with patch(
        "scheduler.schedule_service.data_access.update_schedule",
        side_effect=ValueError("schedule not found."),
    ):
        with pytest.raises(ScheduleNotFoundError):
            service.update_schedule(request, actor)

    session.rollback.assert_called_once()


def test_run_now_rejects_invalid_state() -> None:
    """Ensure run-now rejects schedules outside active/paused states."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    service = ScheduleCommandServiceImpl(session_factory, now_provider=lambda: now)
    actor = _actor_context()
    schedule = _schedule(now)
    schedule.state = "canceled"

    request = ScheduleRunNowRequest(schedule_id=10)

    with (
        patch("scheduler.schedule_service._fetch_schedule", return_value=schedule),
        patch("scheduler.schedule_service.data_access.create_execution") as create_execution,
    ):
        with pytest.raises(ScheduleConflictError):
            service.run_now(request, actor)

    create_execution.assert_not_called()


def test_run_now_builds_scheduled_actor_context() -> None:
    """Ensure run-now uses a scheduled actor context payload."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    service = ScheduleCommandServiceImpl(session_factory, now_provider=lambda: now)
    actor = _actor_context()
    schedule = _schedule(now)
    request = ScheduleRunNowRequest(schedule_id=10)
    execution = Execution(
        id=77,
        task_intent_id=schedule.task_intent_id,
        schedule_id=schedule.id,
        scheduled_for=now,
        created_at=now,
        updated_at=now,
        actor_type="scheduled",
        actor_context=None,
        correlation_id="corr-1",
        status="queued",
        attempt_count=0,
        retry_count=0,
        max_attempts=1,
        failure_count=0,
    )

    with (
        patch("scheduler.schedule_service._fetch_schedule", return_value=schedule),
        patch("scheduler.schedule_service.data_access.record_schedule_audit") as record_audit,
        patch(
            "scheduler.schedule_service.data_access.create_execution",
            return_value=execution,
        ) as create_execution,
    ):
        record_audit.return_value.id = 42
        service.run_now(request, actor)

    execution_actor = create_execution.call_args.args[2]
    assert execution_actor.actor_type == "scheduled"
    assert execution_actor.channel == "scheduled"
    assert "autonomy=limited" in (execution_actor.actor_context or "")
    assert "privilege=constrained" in (execution_actor.actor_context or "")
    assert "requested_by=human@signal" in (execution_actor.actor_context or "")


def test_pause_schedule_returns_audit_linkage() -> None:
    """Ensure pause schedule responses include audit linkage."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    service = ScheduleCommandServiceImpl(session_factory, now_provider=lambda: now)
    actor = _actor_context()
    schedule = _schedule(now)
    intent = _task_intent(now)
    request = SchedulePauseRequest(schedule_id=10, reason="pause-test")

    with (
        patch("scheduler.schedule_service.data_access.pause_schedule", return_value=schedule),
        patch("scheduler.schedule_service._fetch_task_intent", return_value=intent),
        patch("scheduler.schedule_service._fetch_latest_schedule_audit_id", return_value=55),
    ):
        result = service.pause_schedule(request, actor)

    assert result.audit_log_id == 55


def test_run_now_returns_audit_linkage() -> None:
    """Ensure run-now responses include audit linkage."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    service = ScheduleCommandServiceImpl(session_factory, now_provider=lambda: now)
    actor = _actor_context()
    schedule = _schedule(now)
    request = ScheduleRunNowRequest(schedule_id=10)
    execution = Execution(
        id=88,
        task_intent_id=schedule.task_intent_id,
        schedule_id=schedule.id,
        scheduled_for=now,
        created_at=now,
        updated_at=now,
        actor_type="scheduled",
        actor_context=None,
        correlation_id="corr-2",
        status="queued",
        attempt_count=0,
        retry_count=0,
        max_attempts=1,
        failure_count=0,
    )

    with (
        patch("scheduler.schedule_service._fetch_schedule", return_value=schedule),
        patch(
            "scheduler.schedule_service.data_access.create_execution",
            return_value=execution,
        ),
        patch("scheduler.schedule_service.data_access.record_schedule_audit") as record_audit,
    ):
        record_audit.return_value.id = 77
        result = service.run_now(request, actor)

    assert result.audit_log_id == 77
