"""Unit tests for batch reminder aggregation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from commitments.batch_aggregation import list_batch_due_commitments
from commitments.repository import CommitmentCreateInput, CommitmentRepository


def _create_commitment(
    factory: sessionmaker,
    *,
    description: str,
    due_by: datetime | None,
    state: str = "OPEN",
    now: datetime,
) -> int:
    """Create a commitment record for batch aggregation tests."""
    repo = CommitmentRepository(factory)
    record = repo.create(
        CommitmentCreateInput(description=description, due_by=due_by, state=state),
        now=now,
    )
    return record.commitment_id


def test_batch_aggregation_orders_by_urgency(sqlite_session_factory: sessionmaker) -> None:
    """Due commitments should be ordered by urgency descending."""
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    sooner_id = _create_commitment(
        sqlite_session_factory,
        description="Due sooner",
        due_by=now + timedelta(hours=2),
        now=now,
    )
    later_id = _create_commitment(
        sqlite_session_factory,
        description="Due later",
        due_by=now + timedelta(hours=30),
        now=now,
    )

    results = list_batch_due_commitments(
        sqlite_session_factory,
        now=now,
        lookahead_hours=48,
    )

    assert [item.commitment_id for item in results] == [sooner_id, later_id]


def test_batch_aggregation_excludes_non_open(sqlite_session_factory: sessionmaker) -> None:
    """Completed and canceled commitments should be excluded."""
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    open_id = _create_commitment(
        sqlite_session_factory,
        description="Open task",
        due_by=now + timedelta(hours=5),
        state="OPEN",
        now=now,
    )
    _create_commitment(
        sqlite_session_factory,
        description="Completed task",
        due_by=now + timedelta(hours=5),
        state="COMPLETED",
        now=now,
    )
    _create_commitment(
        sqlite_session_factory,
        description="Canceled task",
        due_by=now + timedelta(hours=5),
        state="CANCELED",
        now=now,
    )

    results = list_batch_due_commitments(
        sqlite_session_factory,
        now=now,
        lookahead_hours=24,
    )

    assert [item.commitment_id for item in results] == [open_id]


def test_batch_aggregation_empty_returns_empty(sqlite_session_factory: sessionmaker) -> None:
    """No matches should yield an empty list."""
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    _create_commitment(
        sqlite_session_factory,
        description="Far future",
        due_by=now + timedelta(days=10),
        now=now,
    )
    _create_commitment(
        sqlite_session_factory,
        description="No due date",
        due_by=None,
        now=now,
    )

    results = list_batch_due_commitments(
        sqlite_session_factory,
        now=now,
        lookahead_hours=24,
    )

    assert results == []
