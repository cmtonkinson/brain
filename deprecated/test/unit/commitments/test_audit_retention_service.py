"""Unit tests for commitment audit retention enforcement."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from commitments.audit_retention import enforce_transition_audit_retention
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.state_transition_repository import (
    CommitmentStateTransitionCreateInput,
    CommitmentStateTransitionRepository,
)


def _coerce_utc(value: datetime) -> datetime:
    """Coerce naive datetimes to UTC for assertion consistency."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _create_commitment_id(factory: sessionmaker) -> int:
    """Create a commitment and return its ID."""
    repo = CommitmentRepository(factory)
    commitment = repo.create(CommitmentCreateInput(description="Retention test"))
    return commitment.commitment_id


def _create_transition(
    factory: sessionmaker,
    commitment_id: int,
    *,
    transitioned_at: datetime,
) -> None:
    """Create a transition record with the provided timestamp."""
    repo = CommitmentStateTransitionRepository(factory)
    repo.create(
        CommitmentStateTransitionCreateInput(
            commitment_id=commitment_id,
            from_state="OPEN",
            to_state="COMPLETED",
            actor="user",
            transitioned_at=transitioned_at,
        )
    )


def test_enforce_transition_audit_retention_deletes_old_records(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Retention enforcement removes transitions older than the cutoff window."""
    commitment_id = _create_commitment_id(sqlite_session_factory)
    now = datetime(2025, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
    old_transition = now - timedelta(days=10)
    recent_transition = now - timedelta(days=2)

    _create_transition(sqlite_session_factory, commitment_id, transitioned_at=old_transition)
    _create_transition(sqlite_session_factory, commitment_id, transitioned_at=recent_transition)

    deleted = enforce_transition_audit_retention(
        sqlite_session_factory,
        retention_days=7,
        now=now,
    )

    assert deleted == 1
    remaining = CommitmentStateTransitionRepository(sqlite_session_factory).list_for_commitment(
        commitment_id
    )
    assert len(remaining) == 1
    assert _coerce_utc(remaining[0].transitioned_at) == recent_transition


def test_enforce_transition_audit_retention_noop_when_disabled(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Retention enforcement is a no-op when retention_days is zero."""
    commitment_id = _create_commitment_id(sqlite_session_factory)
    now = datetime(2025, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
    _create_transition(sqlite_session_factory, commitment_id, transitioned_at=now)

    deleted = enforce_transition_audit_retention(
        sqlite_session_factory,
        retention_days=0,
        now=now,
    )

    assert deleted == 0
    remaining = CommitmentStateTransitionRepository(sqlite_session_factory).list_for_commitment(
        commitment_id
    )
    assert len(remaining) == 1
