"""Unit tests for commitment repository CRUD and constraints."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from commitments.repository import (
    CommitmentCreateInput,
    CommitmentRepository,
    CommitmentUpdateInput,
)
from config import settings


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


def _coerce_utc(value: datetime | None) -> datetime | None:
    """Coerce naive datetimes to UTC for assertion consistency."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def test_create_with_defaults(sqlite_session_factory: sessionmaker) -> None:
    """Creating with only a description applies defaults and UTC timestamps."""
    repo = CommitmentRepository(sqlite_session_factory)
    created = repo.create(CommitmentCreateInput(description="Ship the report"))

    assert created.commitment_id is not None
    assert created.description == "Ship the report"
    assert created.state == "OPEN"
    assert created.importance == 2
    assert created.effort_provided == 2
    assert _coerce_utc(created.created_at).tzinfo == timezone.utc
    assert _coerce_utc(created.updated_at).tzinfo == timezone.utc


def test_due_by_datetime_retains_utc(sqlite_session_factory: sessionmaker) -> None:
    """Due_by datetime inputs retain UTC storage."""
    repo = CommitmentRepository(sqlite_session_factory)
    due_by = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    created = repo.create(CommitmentCreateInput(description="Pay invoice", due_by=due_by))

    assert _coerce_utc(created.due_by) == due_by


def test_due_by_date_normalizes_to_local_end_of_day(
    sqlite_session_factory: sessionmaker, monkeypatch
) -> None:
    """Date-only due_by values normalize to 23:59:59 local and convert to UTC."""
    monkeypatch.setattr(settings.user, "timezone", "America/New_York", raising=False)
    repo = CommitmentRepository(sqlite_session_factory)

    created = repo.create(CommitmentCreateInput(description="File taxes", due_by=date(2025, 4, 15)))
    expected = datetime(2025, 4, 16, 3, 59, 59, tzinfo=timezone.utc)

    assert _coerce_utc(created.due_by) == expected


def test_update_persists_description(sqlite_session_factory: sessionmaker) -> None:
    """Updating a commitment persists the new description."""
    repo = CommitmentRepository(sqlite_session_factory)
    created = repo.create(CommitmentCreateInput(description="Draft outline"))

    updated = repo.update(
        created.commitment_id,
        CommitmentUpdateInput(description="Draft full outline"),
    )

    assert updated.description == "Draft full outline"


def test_update_description_sets_last_modified(sqlite_session_factory: sessionmaker) -> None:
    """Updating a description sets last_modified_at for renegotiation tracking."""
    repo = CommitmentRepository(sqlite_session_factory)
    created = repo.create(CommitmentCreateInput(description="Outline report"))
    timestamp = datetime(2025, 2, 1, 9, 0, 0, tzinfo=timezone.utc)

    updated = repo.update(
        created.commitment_id,
        CommitmentUpdateInput(description="Draft report"),
        now=timestamp,
    )

    assert _coerce_utc(updated.last_modified_at) == timestamp


def test_update_respects_explicit_last_modified(sqlite_session_factory: sessionmaker) -> None:
    """Explicit last_modified_at values are preserved during urgency updates."""
    repo = CommitmentRepository(sqlite_session_factory)
    created = repo.create(CommitmentCreateInput(description="Refine spec"))
    explicit = datetime(2025, 2, 2, 10, 0, 0, tzinfo=timezone.utc)
    update_time = datetime(2025, 2, 3, 10, 0, 0, tzinfo=timezone.utc)

    updated = repo.update(
        created.commitment_id,
        CommitmentUpdateInput(effort_provided=3, last_modified_at=explicit),
        now=update_time,
    )

    assert _coerce_utc(updated.last_modified_at) == explicit


def test_delete_removes_commitment(sqlite_session_factory: sessionmaker) -> None:
    """Deleting a commitment removes it from persistence."""
    repo = CommitmentRepository(sqlite_session_factory)
    created = repo.create(CommitmentCreateInput(description="Clean inbox"))

    repo.delete(created.commitment_id)

    fetched = repo.get_by_id(created.commitment_id)
    assert fetched is None


def test_invalid_state_rejected(sqlite_session_factory: sessionmaker) -> None:
    """Invalid commitment states are rejected by constraints."""
    repo = CommitmentRepository(sqlite_session_factory)
    with pytest.raises(IntegrityError):
        repo.create(CommitmentCreateInput(description="Bad state", state="INVALID"))


def test_invalid_importance_rejected(sqlite_session_factory: sessionmaker) -> None:
    """Importance values outside 1-3 are rejected."""
    repo = CommitmentRepository(sqlite_session_factory)
    with pytest.raises(IntegrityError):
        repo.create(CommitmentCreateInput(description="Bad importance", importance=5))


def test_invalid_effort_provided_rejected(sqlite_session_factory: sessionmaker) -> None:
    """Effort_provided values outside 1-3 are rejected."""
    repo = CommitmentRepository(sqlite_session_factory)
    with pytest.raises(IntegrityError):
        repo.create(CommitmentCreateInput(description="Bad effort", effort_provided=0))


def test_invalid_provenance_id_rejected(sqlite_session_factory: sessionmaker) -> None:
    """Invalid provenance references are rejected by foreign keys."""
    repo = CommitmentRepository(_with_foreign_keys(sqlite_session_factory))
    invalid_id = uuid4()

    with pytest.raises(IntegrityError):
        repo.create(CommitmentCreateInput(description="Bad provenance", provenance_id=invalid_id))
