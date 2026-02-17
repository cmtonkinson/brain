"""Integration tests for commitment progress migration and repository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from commitments.progress_repository import (
    CommitmentProgressCreateInput,
    CommitmentProgressRepository,
)
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from config import settings
from models import Artifact, ProvenanceRecord
from services import database


def _ensure_database_ready() -> None:
    """Skip tests when the integration database is not configured or reachable."""
    if not settings.database.url and not settings.database.postgres_password:
        pytest.skip("Integration DB not configured (set DATABASE_URL or POSTGRES_PASSWORD).")
    try:
        with database.get_sync_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Integration DB not reachable: {exc}")


def _create_provenance_id() -> UUID:
    """Create a provenance record and return its ID."""
    now = datetime.now(timezone.utc)
    with database.get_sync_session() as session:
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


def test_insert_and_fetch_progress_records() -> None:
    """Progress records should persist and return ordered by occurred_at desc."""
    _ensure_database_ready()
    database.run_migrations_sync()

    commitment_repo = CommitmentRepository(database.get_sync_session)
    progress_repo = CommitmentProgressRepository(database.get_sync_session)
    commitment = commitment_repo.create(CommitmentCreateInput(description="Progress integration"))
    provenance_id = _create_provenance_id()

    now = datetime.now(timezone.utc)
    progress_repo.create(
        CommitmentProgressCreateInput(
            commitment_id=commitment.commitment_id,
            provenance_id=provenance_id,
            occurred_at=now - timedelta(minutes=5),
            summary="First progress",
            metadata=None,
        )
    )
    progress_repo.create(
        CommitmentProgressCreateInput(
            commitment_id=commitment.commitment_id,
            provenance_id=provenance_id,
            occurred_at=now,
            summary="Second progress",
            metadata={"phase": 2},
        )
    )

    records = progress_repo.list_by_commitment_id(commitment.commitment_id)
    assert [record.summary for record in records] == ["Second progress", "First progress"]

    commitment_repo.delete(commitment.commitment_id)


def test_cascade_delete_removes_progress() -> None:
    """Deleting commitments should cascade to progress records."""
    _ensure_database_ready()
    database.run_migrations_sync()

    commitment_repo = CommitmentRepository(database.get_sync_session)
    progress_repo = CommitmentProgressRepository(database.get_sync_session)
    commitment = commitment_repo.create(CommitmentCreateInput(description="Cascade progress"))
    provenance_id = _create_provenance_id()

    progress_repo.create(
        CommitmentProgressCreateInput(
            commitment_id=commitment.commitment_id,
            provenance_id=provenance_id,
            occurred_at=datetime.now(timezone.utc),
            summary="Cascade progress record",
        )
    )

    commitment_repo.delete(commitment.commitment_id)

    assert progress_repo.list_by_commitment_id(commitment.commitment_id) == []
