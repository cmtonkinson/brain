"""Unit tests for miss detection scheduling behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from commitments.miss_detection_scheduling import MissDetectionScheduleService
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.schedule_link_service import CommitmentScheduleLinkService
from commitments.transition_service import CommitmentStateTransitionService
from models import Schedule
from test.helpers.scheduler_adapter_stub import RecordingSchedulerAdapter
from time_utils import get_local_timezone, to_local


def _create_commitment(
    factory: sessionmaker,
    *,
    description: str,
    due_by: datetime | None = None,
) -> int:
    repo = CommitmentRepository(factory)
    record = repo.create(
        CommitmentCreateInput(
            description=description,
            due_by=due_by,
        )
    )
    return record.commitment_id


def _coerce_local(value: datetime) -> datetime:
    """Coerce naive datetimes to local timezone for comparison."""
    if value.tzinfo is None:
        return value.replace(tzinfo=get_local_timezone())
    return value


def test_create_schedule_and_link(sqlite_session_factory: sessionmaker) -> None:
    """Commitments with due_by should create a miss detection schedule and link."""
    adapter = RecordingSchedulerAdapter()
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=2)
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Pay invoice",
        due_by=due_by,
    )
    service = MissDetectionScheduleService(
        sqlite_session_factory,
        adapter,
        now_provider=lambda: now,
    )

    result = service.ensure_schedule(commitment_id=commitment_id, due_by=due_by)

    assert result.schedule_id is not None
    link_service = CommitmentScheduleLinkService(sqlite_session_factory)
    assert link_service.get_active_schedule_id(commitment_id) == result.schedule_id

    with sqlite_session_factory() as session:
        schedule = session.get(Schedule, result.schedule_id)
        assert schedule is not None
        assert _coerce_local(schedule.run_at) == to_local(due_by)


def test_commitment_without_due_by_does_not_create_schedule(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Commitments without due_by should not have miss detection schedules."""
    adapter = RecordingSchedulerAdapter()
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="No due by",
        due_by=None,
    )
    service = MissDetectionScheduleService(sqlite_session_factory, adapter)

    result = service.ensure_schedule(commitment_id=commitment_id, due_by=None)

    assert result.schedule_id is None
    link_service = CommitmentScheduleLinkService(sqlite_session_factory)
    assert link_service.get_active_schedule_id(commitment_id) is None


def test_due_by_updates_schedule_in_place(sqlite_session_factory: sessionmaker) -> None:
    """Updating due_by should update the existing schedule run_at."""
    adapter = RecordingSchedulerAdapter()
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Update due by",
        due_by=due_by,
    )
    service = MissDetectionScheduleService(
        sqlite_session_factory,
        adapter,
        now_provider=lambda: now,
    )

    created = service.ensure_schedule(commitment_id=commitment_id, due_by=due_by)
    assert created.schedule_id is not None
    updated_due_by = due_by + timedelta(hours=3)

    updated = service.ensure_schedule(commitment_id=commitment_id, due_by=updated_due_by)

    assert updated.schedule_id == created.schedule_id
    with sqlite_session_factory() as session:
        schedule = session.get(Schedule, created.schedule_id)
        assert schedule is not None
        assert _coerce_local(schedule.run_at) == to_local(updated_due_by)


def test_remove_schedule_clears_link(sqlite_session_factory: sessionmaker) -> None:
    """Completing or canceling should remove schedules and deactivate links."""
    adapter = RecordingSchedulerAdapter()
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Remove schedule",
        due_by=due_by,
    )
    service = MissDetectionScheduleService(
        sqlite_session_factory,
        adapter,
        now_provider=lambda: now,
    )
    created = service.ensure_schedule(commitment_id=commitment_id, due_by=due_by)
    assert created.schedule_id is not None

    removed = service.remove_schedule(
        commitment_id=commitment_id,
        reason="completed",
    )

    assert removed.schedule_id == created.schedule_id
    link_service = CommitmentScheduleLinkService(sqlite_session_factory)
    assert link_service.get_active_schedule_id(commitment_id) is None
    with sqlite_session_factory() as session:
        schedule = session.get(Schedule, created.schedule_id)
        assert schedule is not None
        assert schedule.state == "canceled"


def test_transition_hook_removes_schedule(sqlite_session_factory: sessionmaker) -> None:
    """Transition hook should remove miss detection schedules on completion."""
    adapter = RecordingSchedulerAdapter()
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Hook removal",
        due_by=due_by,
    )
    schedule_service = MissDetectionScheduleService(
        sqlite_session_factory,
        adapter,
        now_provider=lambda: now,
    )
    created = schedule_service.ensure_schedule(commitment_id=commitment_id, due_by=due_by)
    assert created.schedule_id is not None

    transition_service = CommitmentStateTransitionService(
        sqlite_session_factory,
        on_completion_hook=lambda cid: schedule_service.remove_schedule(
            commitment_id=cid,
            reason="completed",
        ),
    )
    transition_service.transition(
        commitment_id=commitment_id,
        to_state="COMPLETED",
        actor="user",
    )

    link_service = CommitmentScheduleLinkService(sqlite_session_factory)
    assert link_service.get_active_schedule_id(commitment_id) is None
    with sqlite_session_factory() as session:
        schedule = session.get(Schedule, created.schedule_id)
        assert schedule is not None
        assert schedule.state == "canceled"
