"""Unit tests for loop-closure response actions."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import logging

import pytest
from sqlalchemy.orm import sessionmaker

from commitments.loop_closure_actions import (
    LoopClosureActionRequest,
    LoopClosureActionService,
)
from commitments.loop_closure_parser import LoopClosureIntent
from commitments.miss_detection_scheduling import MissDetectionScheduleService
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.schedule_link_service import CommitmentScheduleLinkService
from commitments.transition_service import CommitmentStateTransitionService
from models import CommitmentStateTransition, Schedule
from test.helpers.scheduler_adapter_stub import RecordingSchedulerAdapter
from time_utils import to_local


def _create_commitment(
    factory: sessionmaker,
    *,
    description: str,
    due_by: datetime | None,
) -> int:
    """Create a commitment and return its id."""
    repo = CommitmentRepository(factory)
    record = repo.create(CommitmentCreateInput(description=description, due_by=due_by))
    return record.commitment_id


def _transition_to_missed(factory: sessionmaker, commitment_id: int, now: datetime) -> None:
    """Transition a commitment to MISSED."""
    CommitmentStateTransitionService(factory).transition(
        commitment_id=commitment_id,
        to_state="MISSED",
        actor="system",
        reason="test_setup",
        now=now,
    )


def _create_schedule(
    factory: sessionmaker,
    adapter: RecordingSchedulerAdapter,
    *,
    commitment_id: int,
    due_by: datetime,
    now: datetime,
) -> int:
    """Create a miss-detection schedule for the commitment and return its id."""
    schedule_service = MissDetectionScheduleService(
        factory,
        adapter,
        now_provider=lambda: now,
    )
    result = schedule_service.ensure_schedule(commitment_id=commitment_id, due_by=due_by)
    assert result.schedule_id is not None
    return result.schedule_id


def _to_local_from_utc(value: datetime) -> datetime:
    """Convert a datetime assumed to be UTC into local time."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return to_local(value)


def test_complete_intent_transitions_state(sqlite_session_factory: sessionmaker, caplog) -> None:
    """Complete intent should transition MISSED commitments to COMPLETED."""
    caplog.set_level(logging.INFO)
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Complete intent",
        due_by=now + timedelta(hours=1),
    )
    _transition_to_missed(sqlite_session_factory, commitment_id, now)
    adapter = RecordingSchedulerAdapter()
    due_by = now + timedelta(hours=1)
    schedule_id = _create_schedule(
        sqlite_session_factory,
        adapter,
        commitment_id=commitment_id,
        due_by=due_by,
        now=now,
    )
    service = LoopClosureActionService(
        sqlite_session_factory,
        adapter,
        now_provider=lambda: now,
    )

    result = service.apply_intent(
        LoopClosureActionRequest(
            commitment_id=commitment_id,
            intent=LoopClosureIntent(intent="complete"),
            prompt="Prompt text",
            response="done",
        )
    )

    assert result.status == "completed"
    updated = CommitmentRepository(sqlite_session_factory).get_by_id(commitment_id)
    assert updated is not None
    assert updated.state == "COMPLETED"
    link_service = CommitmentScheduleLinkService(sqlite_session_factory)
    assert link_service.get_active_schedule_id(commitment_id) is None
    assert schedule_id in adapter.deleted
    with sqlite_session_factory() as session:
        schedule = session.get(Schedule, schedule_id)
        assert schedule is not None
        assert schedule.state == "canceled"
    assert any("Loop-closure response" in record.message for record in caplog.records)


def test_cancel_intent_transitions_with_reason(sqlite_session_factory: sessionmaker) -> None:
    """Cancel intent should transition to CANCELED with reason."""
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Cancel intent",
        due_by=now + timedelta(hours=1),
    )
    _transition_to_missed(sqlite_session_factory, commitment_id, now)
    adapter = RecordingSchedulerAdapter()
    due_by = now + timedelta(hours=1)
    schedule_id = _create_schedule(
        sqlite_session_factory,
        adapter,
        commitment_id=commitment_id,
        due_by=due_by,
        now=now,
    )
    service = LoopClosureActionService(
        sqlite_session_factory,
        adapter,
        now_provider=lambda: now,
    )

    result = service.apply_intent(
        LoopClosureActionRequest(
            commitment_id=commitment_id,
            intent=LoopClosureIntent(intent="cancel"),
            prompt="Prompt text",
            response="cancel",
            reason="user_requested",
        )
    )

    assert result.status == "canceled"
    with sqlite_session_factory() as session:
        transition = (
            session.query(CommitmentStateTransition)
            .filter(CommitmentStateTransition.commitment_id == commitment_id)
            .order_by(CommitmentStateTransition.transition_id.desc())
            .first()
        )
        assert transition is not None
        assert transition.reason == "user_requested"
        schedule = session.get(Schedule, schedule_id)
        assert schedule is not None
        assert schedule.state == "canceled"
    link_service = CommitmentScheduleLinkService(sqlite_session_factory)
    assert link_service.get_active_schedule_id(commitment_id) is None
    assert schedule_id in adapter.deleted


def test_renegotiate_updates_due_by_and_reschedules(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Renegotiate intent should update due_by and schedule."""
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Renegotiate intent",
        due_by=due_by,
    )
    _transition_to_missed(sqlite_session_factory, commitment_id, now)
    service = LoopClosureActionService(
        sqlite_session_factory,
        RecordingSchedulerAdapter(),
        now_provider=lambda: now,
    )
    new_due_by = now + timedelta(days=2)

    result = service.apply_intent(
        LoopClosureActionRequest(
            commitment_id=commitment_id,
            intent=LoopClosureIntent(intent="renegotiate", new_due_by=new_due_by.date()),
            prompt="Prompt text",
            response="reschedule 2026-01-03",
        )
    )

    assert result.status == "renegotiated"
    updated = CommitmentRepository(sqlite_session_factory).get_by_id(commitment_id)
    assert updated is not None
    assert updated.due_by is not None
    assert updated.last_modified_at is not None
    link_service = CommitmentScheduleLinkService(sqlite_session_factory)
    schedule_id = link_service.get_active_schedule_id(commitment_id)
    assert schedule_id is not None
    with sqlite_session_factory() as session:
        schedule = session.get(Schedule, schedule_id)
        assert schedule is not None
        assert to_local(schedule.run_at) == _to_local_from_utc(updated.due_by)


def test_date_only_renegotiate_normalizes_local_timezone(
    sqlite_session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Date-only renegotiation should normalize to end-of-day local time."""
    monkeypatch.setattr("config.settings.user.timezone", "America/New_York", raising=False)
    now = datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc)
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Date-only renegotiate",
        due_by=now + timedelta(hours=1),
    )
    _transition_to_missed(sqlite_session_factory, commitment_id, now)
    service = LoopClosureActionService(
        sqlite_session_factory,
        RecordingSchedulerAdapter(),
        now_provider=lambda: now,
    )
    new_date = date(2026, 2, 15)

    service.apply_intent(
        LoopClosureActionRequest(
            commitment_id=commitment_id,
            intent=LoopClosureIntent(intent="renegotiate", new_due_by=new_date),
            prompt="Prompt text",
            response="reschedule 2026-02-15",
        )
    )

    updated = CommitmentRepository(sqlite_session_factory).get_by_id(commitment_id)
    assert updated is not None
    normalized = updated.due_by
    if normalized is not None and normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    assert normalized == datetime(2026, 2, 16, 4, 59, 59, tzinfo=timezone.utc)


def test_review_intent_updates_reviewed_at_and_keeps_schedule(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Review intent should update reviewed_at without removing schedules."""
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Review intent",
        due_by=due_by,
    )
    _transition_to_missed(sqlite_session_factory, commitment_id, now)
    adapter = RecordingSchedulerAdapter()
    schedule_id = _create_schedule(
        sqlite_session_factory,
        adapter,
        commitment_id=commitment_id,
        due_by=due_by,
        now=now,
    )
    service = LoopClosureActionService(
        sqlite_session_factory,
        adapter,
        now_provider=lambda: now,
    )

    result = service.apply_intent(
        LoopClosureActionRequest(
            commitment_id=commitment_id,
            intent=LoopClosureIntent(intent="review"),
            prompt="Prompt text",
            response="review",
        )
    )

    assert result.status == "reviewed"
    updated = CommitmentRepository(sqlite_session_factory).get_by_id(commitment_id)
    assert updated is not None
    assert updated.state == "MISSED"
    reviewed_at = updated.reviewed_at
    if reviewed_at is not None and reviewed_at.tzinfo is None:
        reviewed_at = reviewed_at.replace(tzinfo=timezone.utc)
    assert reviewed_at == now
    link_service = CommitmentScheduleLinkService(sqlite_session_factory)
    assert link_service.get_active_schedule_id(commitment_id) == schedule_id
    assert schedule_id not in adapter.deleted


def test_resolved_commitment_is_noop(sqlite_session_factory: sessionmaker) -> None:
    """Resolved commitments should return a no-op result."""
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Resolved",
        due_by=now + timedelta(hours=1),
    )
    CommitmentStateTransitionService(sqlite_session_factory).transition(
        commitment_id=commitment_id,
        to_state="COMPLETED",
        actor="user",
        reason="test_setup",
        now=now,
    )
    service = LoopClosureActionService(
        sqlite_session_factory,
        RecordingSchedulerAdapter(),
        now_provider=lambda: now,
    )

    result = service.apply_intent(
        LoopClosureActionRequest(
            commitment_id=commitment_id,
            intent=LoopClosureIntent(intent="complete"),
            prompt="Prompt text",
            response="done",
        )
    )

    assert result.status == "noop"
