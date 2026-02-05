"""Unit tests for commitment review aggregation queries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from commitments.review_aggregation import (
    DEFAULT_REVIEW_EPOCH,
    aggregate_review_commitments,
    get_last_review_run_at,
    list_completed_commitments_since,
    list_missed_commitments_since,
    list_modified_commitments_since,
    list_open_commitments_without_due_by,
    record_review_run,
)
from commitments.repository import (
    CommitmentCreateInput,
    CommitmentRepository,
    CommitmentUpdateInput,
)
from commitments.transition_service import CommitmentStateTransitionService


def _create_commitment(
    factory: sessionmaker,
    *,
    description: str,
    due_by: datetime | None = None,
) -> int:
    """Create a commitment and return its id."""
    repo = CommitmentRepository(factory)
    record = repo.create(CommitmentCreateInput(description=description, due_by=due_by))
    return record.commitment_id


def test_review_run_defaults_to_epoch(sqlite_session_factory: sessionmaker) -> None:
    """Missing review runs should default to the epoch."""
    last_run = get_last_review_run_at(sqlite_session_factory)

    assert last_run == DEFAULT_REVIEW_EPOCH


def test_record_review_run_updates_last_run(
    sqlite_session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recording a review run should update the last run timestamp."""
    monkeypatch.setattr("config.settings.user.timezone", "UTC", raising=False)
    now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    record_review_run(sqlite_session_factory, run_at=now)

    last_run = get_last_review_run_at(sqlite_session_factory)
    assert last_run == now


def test_completed_and_missed_queries(sqlite_session_factory: sessionmaker) -> None:
    """Completed and missed commitments should be queried via transitions."""
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    completed_id = _create_commitment(
        sqlite_session_factory,
        description="Completed commitment",
    )
    missed_id = _create_commitment(
        sqlite_session_factory,
        description="Missed commitment",
    )
    transition_service = CommitmentStateTransitionService(sqlite_session_factory)
    transition_service.transition(
        commitment_id=completed_id,
        to_state="COMPLETED",
        actor="user",
        reason="test",
        now=now + timedelta(hours=1),
    )
    transition_service.transition(
        commitment_id=missed_id,
        to_state="MISSED",
        actor="system",
        reason="test",
        now=now + timedelta(hours=2),
    )

    completed = list_completed_commitments_since(
        sqlite_session_factory,
        since=now + timedelta(minutes=30),
    )
    missed = list_missed_commitments_since(
        sqlite_session_factory,
        since=now + timedelta(minutes=30),
    )

    completed_ids = [item.commitment_id for item in completed]
    missed_ids = [item.commitment_id for item in missed]
    assert completed_id in completed_ids
    assert missed_id in missed_ids


def test_modified_commitments_query(sqlite_session_factory: sessionmaker) -> None:
    """Modified commitments should be detected via last_modified_at."""
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Modified commitment",
        due_by=now + timedelta(hours=1),
    )
    repo = CommitmentRepository(sqlite_session_factory)
    repo.update(
        commitment_id,
        CommitmentUpdateInput(due_by=now + timedelta(days=2)),
        now=now + timedelta(hours=2),
    )

    modified = list_modified_commitments_since(
        sqlite_session_factory,
        since=now + timedelta(minutes=30),
    )

    assert [item.commitment_id for item in modified] == [commitment_id]


def test_open_commitments_without_due_by(sqlite_session_factory: sessionmaker) -> None:
    """OPEN commitments with no due_by should be included."""
    open_id = _create_commitment(sqlite_session_factory, description="Open no due by")
    _create_commitment(
        sqlite_session_factory,
        description="Open with due by",
        due_by=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
    )

    rows = list_open_commitments_without_due_by(sqlite_session_factory)
    assert [item.commitment_id for item in rows] == [open_id]


def test_aggregate_handles_empty_sets(sqlite_session_factory: sessionmaker) -> None:
    """Aggregation should handle empty result sets without errors."""
    result = aggregate_review_commitments(sqlite_session_factory)

    assert result.completed == []
    assert result.missed == []
    assert result.modified == []
    assert result.no_due_by == []
