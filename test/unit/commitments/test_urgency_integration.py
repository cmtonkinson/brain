"""Unit tests for urgency lifecycle integration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from commitments.repository import (
    CommitmentCreateInput,
    CommitmentRepository,
    CommitmentUpdateInput,
)
from commitments.urgency import compute_urgency
from models import CommitmentScheduleLink, Schedule, TaskIntent
from time_utils import to_utc


def _create_schedule_id(factory: sessionmaker, *, next_run_at: datetime) -> int:
    """Create a schedule and return its ID."""
    now = datetime.now(timezone.utc)
    with factory() as session:
        intent = TaskIntent(
            summary="Follow up",
            details=None,
            creator_actor_type="system",
            creator_actor_id=None,
            creator_channel="tests",
            origin_reference=None,
            superseded_by_intent_id=None,
            created_at=now,
            updated_at=now,
        )
        session.add(intent)
        session.flush()
        schedule = Schedule(
            task_intent_id=intent.id,
            schedule_type="one_time",
            state="active",
            timezone="UTC",
            next_run_at=next_run_at,
            last_run_at=None,
            last_run_status=None,
            failure_count=0,
            last_execution_id=None,
            created_by_actor_type="system",
            created_by_actor_id=None,
            created_at=now,
            updated_at=now,
        )
        session.add(schedule)
        session.commit()
        return schedule.id


def test_create_computes_urgency(sqlite_session_factory: sessionmaker) -> None:
    """Creating a commitment should compute urgency."""
    repo = CommitmentRepository(sqlite_session_factory)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=2)

    created = repo.create(
        CommitmentCreateInput(
            description="Urgency test",
            importance=3,
            effort_provided=1,
            due_by=due_by,
        ),
        now=now,
    )

    expected = compute_urgency(3, 1, due_by, now)
    assert created.urgency == expected


def test_update_importance_recalculates_urgency_and_last_modified(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Updating importance recalculates urgency and sets last_modified_at."""
    repo = CommitmentRepository(sqlite_session_factory)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=4)
    commitment = repo.create(
        CommitmentCreateInput(description="Update urgency", due_by=due_by),
        now=now,
    )

    updated_at = now + timedelta(hours=1)
    updated = repo.update(
        commitment.commitment_id,
        CommitmentUpdateInput(importance=3),
        now=updated_at,
    )

    normalized_due_by = to_utc(updated.due_by) if updated.due_by else None
    expected = compute_urgency(
        updated.importance,
        updated.effort_provided,
        normalized_due_by,
        updated_at,
    )
    assert updated.urgency == expected
    assert updated.last_modified_at == updated_at


def test_update_description_does_not_recalculate(sqlite_session_factory: sessionmaker) -> None:
    """Updating description should not recalculate urgency or last_modified_at."""
    repo = CommitmentRepository(sqlite_session_factory)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=4)
    commitment = repo.create(
        CommitmentCreateInput(description="No recalc", due_by=due_by),
        now=now,
    )

    updated = repo.update(
        commitment.commitment_id,
        CommitmentUpdateInput(description="Still no recalc"),
        now=now + timedelta(hours=1),
    )

    assert updated.urgency == commitment.urgency
    assert updated.last_modified_at == commitment.last_modified_at


def test_high_urgency_far_schedule_logs_warning(
    sqlite_session_factory: sessionmaker,
    caplog,
) -> None:
    """High urgency commitments with far schedules should log warnings."""
    repo = CommitmentRepository(sqlite_session_factory)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    commitment = repo.create(
        CommitmentCreateInput(
            description="High urgency",
            importance=3,
            effort_provided=3,
            due_by=now - timedelta(hours=1),
        ),
        now=now,
    )
    schedule_id = _create_schedule_id(
        sqlite_session_factory,
        next_run_at=now + timedelta(hours=72),
    )
    with sqlite_session_factory() as session:
        session.add(
            CommitmentScheduleLink(
                commitment_id=commitment.commitment_id,
                schedule_id=schedule_id,
                created_at=now,
                is_active=True,
            )
        )
        session.commit()

    caplog.set_level("WARNING")

    repo.update(
        commitment.commitment_id,
        CommitmentUpdateInput(due_by=now - timedelta(hours=2)),
        now=now + timedelta(minutes=5),
    )

    assert "High urgency commitment has distant schedule" in caplog.text
