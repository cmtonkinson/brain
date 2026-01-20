"""Unit tests for the schedule command service handlers."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from models import Schedule, TaskIntent
from scheduler.adapter_interface import SchedulePayload, SchedulerAdapter, SchedulerAdapterError
from scheduler.schedule_service import ScheduleCommandServiceImpl
from scheduler.schedule_service_interface import (
    ActorContext,
    ScheduleAdapterSyncError,
    ScheduleConflictError,
    ScheduleCreateRequest,
    ScheduleDeleteRequest,
    ScheduleNotFoundError,
    SchedulePauseRequest,
    ScheduleResumeRequest,
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
    adapter = MagicMock(spec=SchedulerAdapter)
    service = ScheduleCommandServiceImpl(session_factory, adapter, now_provider=lambda: now)
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
    adapter.register_schedule.assert_called_once()
    create_mock.assert_called_once()
    session.commit.assert_called_once()


def test_update_schedule_maps_not_found() -> None:
    """Ensure not-found errors are mapped on update."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    adapter = MagicMock(spec=SchedulerAdapter)
    service = ScheduleCommandServiceImpl(session_factory, adapter, now_provider=lambda: now)
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
    adapter = MagicMock(spec=SchedulerAdapter)
    service = ScheduleCommandServiceImpl(session_factory, adapter, now_provider=lambda: now)
    actor = _actor_context()
    schedule = _schedule(now)
    schedule.state = "canceled"

    request = ScheduleRunNowRequest(schedule_id=10)

    with patch("scheduler.schedule_service._fetch_schedule", return_value=schedule):
        with pytest.raises(ScheduleConflictError):
            service.run_now(request, actor)

    adapter.trigger_callback.assert_not_called()


def test_run_now_triggers_adapter_callback() -> None:
    """Ensure run-now schedules an immediate adapter callback."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    adapter = MagicMock(spec=SchedulerAdapter)
    service = ScheduleCommandServiceImpl(session_factory, adapter, now_provider=lambda: now)
    actor = _actor_context()
    schedule = _schedule(now)
    request = ScheduleRunNowRequest(schedule_id=10)

    with (
        patch("scheduler.schedule_service._fetch_schedule", return_value=schedule),
        patch("scheduler.schedule_service.data_access.record_schedule_audit") as record_audit,
    ):
        record_audit.return_value.id = 42
        result = service.run_now(request, actor)

    adapter.trigger_callback.assert_called_once_with(
        schedule.id,
        result.scheduled_for,
        trace_id=actor.trace_id,
    )


def test_pause_schedule_returns_audit_linkage() -> None:
    """Ensure pause schedule responses include audit linkage."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    adapter = MagicMock(spec=SchedulerAdapter)
    service = ScheduleCommandServiceImpl(session_factory, adapter, now_provider=lambda: now)
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
    adapter.pause_schedule.assert_called_once_with(schedule.id)


def test_run_now_returns_audit_linkage() -> None:
    """Ensure run-now responses include audit linkage."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    adapter = MagicMock(spec=SchedulerAdapter)
    service = ScheduleCommandServiceImpl(session_factory, adapter, now_provider=lambda: now)
    actor = _actor_context()
    schedule = _schedule(now)
    request = ScheduleRunNowRequest(schedule_id=10)

    with (
        patch("scheduler.schedule_service._fetch_schedule", return_value=schedule),
        patch("scheduler.schedule_service.data_access.record_schedule_audit") as record_audit,
    ):
        record_audit.return_value.id = 77
        result = service.run_now(request, actor)

    assert result.audit_log_id == 77


def test_update_schedule_syncs_adapter_payload() -> None:
    """Ensure update schedule sends adapter update payloads."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    adapter = MagicMock(spec=SchedulerAdapter)
    service = ScheduleCommandServiceImpl(session_factory, adapter, now_provider=lambda: now)
    actor = _actor_context()
    schedule = _schedule(now)
    intent = _task_intent(now)

    request = ScheduleUpdateRequest(
        schedule_id=10,
        definition=ScheduleDefinitionInput(interval_count=2, interval_unit="day"),
    )

    with (
        patch("scheduler.schedule_service.data_access.update_schedule", return_value=schedule),
        patch("scheduler.schedule_service._fetch_task_intent", return_value=intent),
        patch("scheduler.schedule_service._fetch_latest_schedule_audit_id", return_value=9),
    ):
        service.update_schedule(request, actor)

    payload = adapter.update_schedule.call_args.args[0]
    assert isinstance(payload, SchedulePayload)
    assert payload.schedule_id == schedule.id
    assert payload.schedule_type == str(schedule.schedule_type)


def test_delete_schedule_calls_adapter_delete() -> None:
    """Ensure delete schedule removes adapter registrations."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    adapter = MagicMock(spec=SchedulerAdapter)
    service = ScheduleCommandServiceImpl(session_factory, adapter, now_provider=lambda: now)
    actor = _actor_context()
    schedule = _schedule(now)

    with (
        patch("scheduler.schedule_service.data_access.delete_schedule", return_value=schedule),
        patch("scheduler.schedule_service._fetch_latest_schedule_audit_id", return_value=88),
    ):
        service.delete_schedule(ScheduleDeleteRequest(schedule_id=schedule.id), actor)

    adapter.delete_schedule.assert_called_once_with(schedule.id)


def test_resume_schedule_calls_adapter_resume() -> None:
    """Ensure resume schedule resumes adapter registrations."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    adapter = MagicMock(spec=SchedulerAdapter)
    service = ScheduleCommandServiceImpl(session_factory, adapter, now_provider=lambda: now)
    actor = _actor_context()
    schedule = _schedule(now)
    intent = _task_intent(now)

    with (
        patch("scheduler.schedule_service.data_access.resume_schedule", return_value=schedule),
        patch("scheduler.schedule_service._fetch_task_intent", return_value=intent),
        patch("scheduler.schedule_service._fetch_latest_schedule_audit_id", return_value=11),
    ):
        service.resume_schedule(ScheduleResumeRequest(schedule_id=schedule.id), actor)

    adapter.resume_schedule.assert_called_once_with(schedule.id)


def test_adapter_sync_failure_is_reported() -> None:
    """Ensure adapter sync failures raise a schedule adapter error."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    adapter = MagicMock(spec=SchedulerAdapter)
    adapter.delete_schedule.side_effect = SchedulerAdapterError("boom", "Adapter down.")
    service = ScheduleCommandServiceImpl(session_factory, adapter, now_provider=lambda: now)
    actor = _actor_context()
    schedule = _schedule(now)

    with (
        patch("scheduler.schedule_service.data_access.delete_schedule", return_value=schedule),
        patch("scheduler.schedule_service._fetch_latest_schedule_audit_id", return_value=88),
        patch("scheduler.schedule_service.data_access.record_schedule_audit"),
    ):
        with pytest.raises(ScheduleAdapterSyncError):
            service.delete_schedule(ScheduleDeleteRequest(schedule_id=schedule.id), actor)
