"""Unit tests for batch reminder formatting."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from commitments.batch_formatting import format_batch_reminder_message
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from time_utils import to_local


def _create_commitment(
    factory: sessionmaker,
    *,
    description: str,
    due_by: datetime | None,
    now: datetime,
) -> int:
    """Create a commitment record for formatting tests."""
    repo = CommitmentRepository(factory)
    record = repo.create(
        CommitmentCreateInput(description=description, due_by=due_by),
        now=now,
    )
    return record.commitment_id


def _load_commitment(factory: sessionmaker, commitment_id: int):
    """Load a commitment record for assertions."""
    repo = CommitmentRepository(factory)
    record = repo.get_by_id(commitment_id)
    assert record is not None
    return record


def test_batch_formatting_includes_descriptions_and_due_times(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Formatting should include descriptions and due times in order."""
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    first_id = _create_commitment(
        sqlite_session_factory,
        description="First task",
        due_by=now.replace(hour=10),
        now=now,
    )
    second_id = _create_commitment(
        sqlite_session_factory,
        description="Second task",
        due_by=now.replace(hour=12),
        now=now,
    )
    first = _load_commitment(sqlite_session_factory, first_id)
    second = _load_commitment(sqlite_session_factory, second_id)

    message = format_batch_reminder_message([first, second])

    first_due = to_local(first.due_by).strftime("%Y-%m-%d %H:%M %Z")
    second_due = to_local(second.due_by).strftime("%Y-%m-%d %H:%M %Z")

    assert "Daily reminders:" in message
    assert f"First task (due {first_due})" in message
    assert f"Second task (due {second_due})" in message
    assert message.index("First task") < message.index("Second task")


def test_batch_formatting_single_item(sqlite_session_factory: sessionmaker) -> None:
    """Single-item batches should format cleanly."""
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Solo task",
        due_by=now.replace(hour=9),
        now=now,
    )
    commitment = _load_commitment(sqlite_session_factory, commitment_id)

    message = format_batch_reminder_message([commitment])

    due_time = to_local(commitment.due_by).strftime("%Y-%m-%d %H:%M %Z")
    assert message.splitlines()[0] == "Daily reminders:"
    assert f"Solo task (due {due_time})" in message
