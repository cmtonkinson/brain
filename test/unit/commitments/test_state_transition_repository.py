"""Unit tests for commitment state transition repository behavior."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.state_transition_repository import (
    CommitmentStateTransitionCreateInput,
    CommitmentStateTransitionRepository,
    build_retention_cleanup_query,
)


def _coerce_utc(value: datetime | None) -> datetime | None:
    """Coerce naive datetimes to UTC for assertion consistency."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
    commitment = repo.create(CommitmentCreateInput(description="Draft report"))
    return commitment.commitment_id


def test_create_transition_happy_path(sqlite_session_factory: sessionmaker) -> None:
    """Creating a transition persists required fields and normalizes timestamps."""
    commitment_id = _create_commitment_id(sqlite_session_factory)
    repo = CommitmentStateTransitionRepository(sqlite_session_factory)
    transitioned_at = datetime(2025, 2, 1, 12, 30, 0)

    created = repo.create(
        CommitmentStateTransitionCreateInput(
            commitment_id=commitment_id,
            from_state="OPEN",
            to_state="COMPLETED",
            actor="user",
            reason="Finished early",
            transitioned_at=transitioned_at,
        )
    )

    assert created.transition_id is not None
    assert created.commitment_id == commitment_id
    assert created.from_state == "OPEN"
    assert created.to_state == "COMPLETED"
    assert created.actor == "user"
    assert created.reason == "Finished early"
    assert _coerce_utc(created.transitioned_at).tzinfo == timezone.utc


def test_invalid_state_rejected(sqlite_session_factory: sessionmaker) -> None:
    """Invalid state values are rejected by constraints."""
    commitment_id = _create_commitment_id(sqlite_session_factory)
    repo = CommitmentStateTransitionRepository(sqlite_session_factory)

    with pytest.raises(IntegrityError):
        repo.create(
            CommitmentStateTransitionCreateInput(
                commitment_id=commitment_id,
                from_state="INVALID",
                to_state="OPEN",
                actor="user",
            )
        )


def test_invalid_actor_rejected(sqlite_session_factory: sessionmaker) -> None:
    """Invalid actor values are rejected by constraints."""
    commitment_id = _create_commitment_id(sqlite_session_factory)
    repo = CommitmentStateTransitionRepository(sqlite_session_factory)

    with pytest.raises(IntegrityError):
        repo.create(
            CommitmentStateTransitionCreateInput(
                commitment_id=commitment_id,
                from_state="OPEN",
                to_state="COMPLETED",
                actor="robot",
            )
        )


def test_invalid_confidence_rejected(sqlite_session_factory: sessionmaker) -> None:
    """Confidence values outside 0-1 are rejected."""
    commitment_id = _create_commitment_id(sqlite_session_factory)
    repo = CommitmentStateTransitionRepository(sqlite_session_factory)

    with pytest.raises(IntegrityError):
        repo.create(
            CommitmentStateTransitionCreateInput(
                commitment_id=commitment_id,
                from_state="OPEN",
                to_state="COMPLETED",
                actor="system",
                confidence=1.5,
            )
        )


def test_history_ordered_desc(sqlite_session_factory: sessionmaker) -> None:
    """History results are ordered by transitioned_at descending."""
    commitment_id = _create_commitment_id(sqlite_session_factory)
    repo = CommitmentStateTransitionRepository(sqlite_session_factory)

    earlier = datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    later = datetime(2025, 1, 2, 9, 0, 0, tzinfo=timezone.utc)

    repo.create(
        CommitmentStateTransitionCreateInput(
            commitment_id=commitment_id,
            from_state="OPEN",
            to_state="MISSED",
            actor="system",
            transitioned_at=earlier,
        )
    )
    repo.create(
        CommitmentStateTransitionCreateInput(
            commitment_id=commitment_id,
            from_state="MISSED",
            to_state="COMPLETED",
            actor="user",
            transitioned_at=later,
        )
    )

    history = repo.list_for_commitment(commitment_id)

    assert [_coerce_utc(item.transitioned_at) for item in history] == [later, earlier]


def test_cascade_delete_removes_transitions(sqlite_session_factory: sessionmaker) -> None:
    """Deleting a commitment cascades to delete its transitions."""
    factory = _with_foreign_keys(sqlite_session_factory)
    commitment_repo = CommitmentRepository(factory)
    transition_repo = CommitmentStateTransitionRepository(factory)
    commitment = commitment_repo.create(CommitmentCreateInput(description="Cascade test"))

    transition_repo.create(
        CommitmentStateTransitionCreateInput(
            commitment_id=commitment.commitment_id,
            from_state="OPEN",
            to_state="CANCELED",
            actor="user",
        )
    )

    commitment_repo.delete(commitment.commitment_id)

    assert transition_repo.list_for_commitment(commitment.commitment_id) == []


def test_retention_cleanup_query_requires_positive_days() -> None:
    """Retention cleanup SQL helper enforces positive day counts."""
    with pytest.raises(ValueError):
        build_retention_cleanup_query(0)
