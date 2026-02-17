"""Unit tests for commitment progress repository behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from commitments.progress_repository import (
    CommitmentProgressCreateInput,
    CommitmentProgressRepository,
)
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from models import Artifact, ProvenanceRecord


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
    commitment = repo.create(CommitmentCreateInput(description="Progress test"))
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


def test_insert_and_fetch_progress_records_ordered(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Progress records should return ordered by occurred_at descending."""
    commitment_id = _create_commitment_id(sqlite_session_factory)
    provenance_id = _create_provenance_id(sqlite_session_factory)
    repo = CommitmentProgressRepository(sqlite_session_factory)

    now = datetime.now(timezone.utc)
    repo.create(
        CommitmentProgressCreateInput(
            commitment_id=commitment_id,
            provenance_id=provenance_id,
            occurred_at=now - timedelta(hours=1),
            summary="First update",
            snippet="snippet-1",
            metadata={"step": 1},
        )
    )
    repo.create(
        CommitmentProgressCreateInput(
            commitment_id=commitment_id,
            provenance_id=provenance_id,
            occurred_at=now,
            summary="Second update",
            snippet="snippet-2",
            metadata={"step": 2},
        )
    )

    records = repo.list_by_commitment_id(commitment_id)
    assert [record.summary for record in records] == ["Second update", "First update"]


def test_metadata_and_snippet_allow_null(sqlite_session_factory: sessionmaker) -> None:
    """Snippet and metadata fields should accept null values."""
    commitment_id = _create_commitment_id(sqlite_session_factory)
    provenance_id = _create_provenance_id(sqlite_session_factory)
    repo = CommitmentProgressRepository(sqlite_session_factory)

    record = repo.create(
        CommitmentProgressCreateInput(
            commitment_id=commitment_id,
            provenance_id=provenance_id,
            occurred_at=datetime.now(timezone.utc),
            summary="Null fields",
            snippet=None,
            metadata=None,
        )
    )

    assert record.snippet is None
    assert record.metadata_ is None


def test_cascade_delete_removes_progress(sqlite_session_factory: sessionmaker) -> None:
    """Deleting a commitment should cascade to its progress records."""
    factory = _with_foreign_keys(sqlite_session_factory)
    commitment_id = _create_commitment_id(factory)
    provenance_id = _create_provenance_id(factory)
    repo = CommitmentProgressRepository(factory)

    repo.create(
        CommitmentProgressCreateInput(
            commitment_id=commitment_id,
            provenance_id=provenance_id,
            occurred_at=datetime.now(timezone.utc),
            summary="Cascade check",
        )
    )

    commitment_repo = CommitmentRepository(factory)
    commitment_repo.delete(commitment_id)

    assert repo.list_by_commitment_id(commitment_id) == []
