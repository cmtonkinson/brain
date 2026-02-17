"""Unit tests for commitment schedule link service behavior."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.schedule_link_service import CommitmentScheduleLinkService
from models import Commitment, CommitmentScheduleLink, Schedule, TaskIntent


def _create_commitment_id(factory: sessionmaker) -> int:
    """Create a commitment and return its ID."""
    repo = CommitmentRepository(factory)
    commitment = repo.create(CommitmentCreateInput(description="Link schedule"))
    return commitment.commitment_id


def _create_schedule_id(factory: sessionmaker) -> int:
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
            next_run_at=None,
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


def test_create_link_updates_next_schedule_id(sqlite_session_factory: sessionmaker) -> None:
    """Creating a link should update next_schedule_id and set active link."""
    service = CommitmentScheduleLinkService(sqlite_session_factory)
    commitment_id = _create_commitment_id(sqlite_session_factory)
    schedule_id = _create_schedule_id(sqlite_session_factory)

    service.create_link(commitment_id=commitment_id, schedule_id=schedule_id)

    with sqlite_session_factory() as session:
        commitment = session.get(Commitment, commitment_id)
        assert commitment is not None
        assert commitment.next_schedule_id == schedule_id
        active_links = (
            session.query(CommitmentScheduleLink)
            .filter(
                CommitmentScheduleLink.commitment_id == commitment_id,
                CommitmentScheduleLink.is_active.is_(True),
            )
            .all()
        )
        assert len(active_links) == 1
        assert active_links[0].schedule_id == schedule_id


def test_create_link_deactivates_previous(sqlite_session_factory: sessionmaker) -> None:
    """Creating a second link should deactivate the first and update next_schedule_id."""
    service = CommitmentScheduleLinkService(sqlite_session_factory)
    commitment_id = _create_commitment_id(sqlite_session_factory)
    first_schedule_id = _create_schedule_id(sqlite_session_factory)
    second_schedule_id = _create_schedule_id(sqlite_session_factory)

    service.create_link(commitment_id=commitment_id, schedule_id=first_schedule_id)
    service.create_link(commitment_id=commitment_id, schedule_id=second_schedule_id)

    with sqlite_session_factory() as session:
        commitment = session.get(Commitment, commitment_id)
        assert commitment is not None
        assert commitment.next_schedule_id == second_schedule_id

        active_links = (
            session.query(CommitmentScheduleLink)
            .filter(
                CommitmentScheduleLink.commitment_id == commitment_id,
                CommitmentScheduleLink.is_active.is_(True),
            )
            .all()
        )
        assert len(active_links) == 1
        assert active_links[0].schedule_id == second_schedule_id

        inactive_links = (
            session.query(CommitmentScheduleLink)
            .filter(
                CommitmentScheduleLink.commitment_id == commitment_id,
                CommitmentScheduleLink.is_active.is_(False),
            )
            .all()
        )
        assert any(link.schedule_id == first_schedule_id for link in inactive_links)


def test_deactivate_link_clears_next_schedule_id(sqlite_session_factory: sessionmaker) -> None:
    """Deactivating a link should clear next_schedule_id."""
    service = CommitmentScheduleLinkService(sqlite_session_factory)
    commitment_id = _create_commitment_id(sqlite_session_factory)
    schedule_id = _create_schedule_id(sqlite_session_factory)

    service.create_link(commitment_id=commitment_id, schedule_id=schedule_id)
    service.deactivate_link(commitment_id=commitment_id, schedule_id=schedule_id)

    with sqlite_session_factory() as session:
        commitment = session.get(Commitment, commitment_id)
        assert commitment is not None
        assert commitment.next_schedule_id is None
        link = (
            session.query(CommitmentScheduleLink)
            .filter(
                CommitmentScheduleLink.commitment_id == commitment_id,
                CommitmentScheduleLink.schedule_id == schedule_id,
            )
            .one()
        )
        assert link.is_active is False
