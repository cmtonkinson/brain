"""Unit tests for commitment schedule link repository behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.schedule_links import (
    CommitmentScheduleLinkCreateInput,
    CommitmentScheduleLinkRepository,
)
from models import Schedule, TaskIntent


def _enable_foreign_keys(session) -> None:
    """Enable SQLite foreign key enforcement for a session."""
    session.execute(text("PRAGMA foreign_keys=ON"))


def _with_foreign_keys(factory: sessionmaker) -> sessionmaker:
    """Wrap a session factory to enable SQLite foreign keys on each session."""

    def _factory():
        session = factory()
        _enable_foreign_keys(session)
        return session

    return _factory


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


def test_create_and_resolve_active_link(sqlite_session_factory: sessionmaker) -> None:
    """Creating a link allows resolving a commitment by schedule_id."""
    commitment_id = _create_commitment_id(sqlite_session_factory)
    schedule_id = _create_schedule_id(sqlite_session_factory)
    repo = CommitmentScheduleLinkRepository(sqlite_session_factory)

    repo.create(
        CommitmentScheduleLinkCreateInput(
            commitment_id=commitment_id,
            schedule_id=schedule_id,
        )
    )

    resolved = repo.resolve_commitment_by_schedule_id(schedule_id)
    assert resolved is not None
    assert resolved.commitment_id == commitment_id


def test_resolve_returns_none_for_inactive_link(sqlite_session_factory: sessionmaker) -> None:
    """Inactive links should not resolve to a commitment."""
    commitment_id = _create_commitment_id(sqlite_session_factory)
    schedule_id = _create_schedule_id(sqlite_session_factory)
    repo = CommitmentScheduleLinkRepository(sqlite_session_factory)

    repo.create(
        CommitmentScheduleLinkCreateInput(
            commitment_id=commitment_id,
            schedule_id=schedule_id,
        )
    )
    repo.deactivate(commitment_id, schedule_id)

    assert repo.resolve_commitment_by_schedule_id(schedule_id) is None


def test_deactivate_sets_is_active_false(sqlite_session_factory: sessionmaker) -> None:
    """Deactivating a link sets is_active to false without deleting it."""
    commitment_id = _create_commitment_id(sqlite_session_factory)
    schedule_id = _create_schedule_id(sqlite_session_factory)
    repo = CommitmentScheduleLinkRepository(sqlite_session_factory)

    created = repo.create(
        CommitmentScheduleLinkCreateInput(
            commitment_id=commitment_id,
            schedule_id=schedule_id,
        )
    )

    updated = repo.deactivate(commitment_id, schedule_id)

    assert created.commitment_id == updated.commitment_id
    assert updated.is_active is False


def test_cascade_delete_removes_links(sqlite_session_factory: sessionmaker) -> None:
    """Deleting a commitment cascades to delete its schedule links."""
    factory = _with_foreign_keys(sqlite_session_factory)
    commitment_repo = CommitmentRepository(factory)
    link_repo = CommitmentScheduleLinkRepository(factory)

    commitment = commitment_repo.create(CommitmentCreateInput(description="Cascade"))
    schedule_id = _create_schedule_id(factory)

    link_repo.create(
        CommitmentScheduleLinkCreateInput(
            commitment_id=commitment.commitment_id,
            schedule_id=schedule_id,
        )
    )

    commitment_repo.delete(commitment.commitment_id)

    assert link_repo.resolve_commitment_by_schedule_id(schedule_id) is None


def test_resolve_returns_none_for_missing_schedule(sqlite_session_factory: sessionmaker) -> None:
    """Missing schedule links should return None."""
    repo = CommitmentScheduleLinkRepository(sqlite_session_factory)

    assert repo.resolve_commitment_by_schedule_id(9999) is None
