"""Unit tests for progress recording service behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from commitments.progress_repository import CommitmentProgressRepository
from commitments.progress_service import CommitmentProgressService
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from models import Artifact, ProvenanceRecord
from time_utils import to_utc


def _coerce_utc(value: datetime) -> datetime:
    """Coerce naive datetimes to UTC for comparison."""
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
    commitment = repo.create(CommitmentCreateInput(description="Progress service"))
    return commitment.commitment_id


def _create_provenance_id(factory: sessionmaker) -> UUID:
    """Create a provenance record and return its ID."""
    now = datetime.now(timezone.utc)
    with factory() as session:
        artifact = Artifact(
            object_key=f"b1:sha256:{uuid4().hex}",
            created_at=now,
            size_bytes=4,
            mime_type=None,
            checksum="deadbeef",
            artifact_type="raw",
            first_ingested_at=now,
            last_ingested_at=now,
            parent_object_key=None,
            parent_stage=None,
        )
        session.add(artifact)
        session.flush()
        record = ProvenanceRecord(
            object_key=artifact.object_key,
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        session.commit()
        return record.id


def test_record_progress_updates_last_progress_at(sqlite_session_factory: sessionmaker) -> None:
    """Recording progress should update last_progress_at and persist the record."""
    commitment_id = _create_commitment_id(sqlite_session_factory)
    provenance_id = _create_provenance_id(sqlite_session_factory)
    service = CommitmentProgressService(sqlite_session_factory)
    repo = CommitmentRepository(sqlite_session_factory)

    occurred_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    record = service.record_progress(
        commitment_id=commitment_id,
        provenance_id=provenance_id,
        occurred_at=occurred_at,
        summary="Did some work",
    )

    updated = repo.get_by_id(commitment_id)
    assert updated is not None
    assert _coerce_utc(updated.last_progress_at) == to_utc(occurred_at)

    progress = CommitmentProgressRepository(sqlite_session_factory).list_by_commitment_id(
        commitment_id
    )
    assert len(progress) == 1
    assert progress[0].progress_id == record.progress_id


def test_invalid_commitment_id_raises(sqlite_session_factory: sessionmaker) -> None:
    """Missing commitments should raise errors when recording progress."""
    service = CommitmentProgressService(sqlite_session_factory)
    provenance_id = _create_provenance_id(sqlite_session_factory)

    with pytest.raises(ValueError):
        service.record_progress(
            commitment_id=9999,
            provenance_id=provenance_id,
            occurred_at=datetime.now(timezone.utc),
            summary="Invalid",
        )


def test_insert_failure_rolls_back_last_progress_at(sqlite_session_factory: sessionmaker) -> None:
    """Insert failures should not update last_progress_at."""
    factory = _with_foreign_keys(sqlite_session_factory)
    commitment_id = _create_commitment_id(factory)
    service = CommitmentProgressService(factory)
    repo = CommitmentRepository(factory)

    with pytest.raises(IntegrityError):
        service.record_progress(
            commitment_id=commitment_id,
            provenance_id=uuid4(),
            occurred_at=datetime.now(timezone.utc),
            summary="Bad provenance",
        )

    refreshed = repo.get_by_id(commitment_id)
    assert refreshed is not None
    assert refreshed.last_progress_at is None
