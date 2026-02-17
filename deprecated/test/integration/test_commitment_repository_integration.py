"""Integration tests for commitment repository CRUD and constraints."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text

from commitments.repository import (
    CommitmentCreateInput,
    CommitmentRepository,
    CommitmentUpdateInput,
)
from config import settings
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


def test_commitment_crud_defaults_and_due_by(monkeypatch) -> None:
    """Commitments persist with defaults, UTC timestamps, and due_by normalization."""
    _ensure_database_ready()
    database.run_migrations_sync()
    monkeypatch.setattr(settings.user, "timezone", "America/New_York", raising=False)

    repo = CommitmentRepository(database.get_sync_session)
    created = repo.create(
        CommitmentCreateInput(description="Integrate commitments", due_by=date(2025, 4, 15))
    )

    assert created.state == "OPEN"
    assert created.importance == 2
    assert created.effort_provided == 2
    assert created.created_at.tzinfo is not None
    assert created.updated_at.tzinfo is not None
    assert created.due_by == datetime(2025, 4, 16, 3, 59, 59, tzinfo=timezone.utc)

    updated = repo.update(
        created.commitment_id,
        CommitmentUpdateInput(description="Integrate commitment tracking"),
    )
    assert updated.description == "Integrate commitment tracking"

    repo.delete(created.commitment_id)
    assert repo.get_by_id(created.commitment_id) is None


def test_commitment_constraints_enforced() -> None:
    """Database constraints reject invalid commitment values."""
    _ensure_database_ready()
    database.run_migrations_sync()

    repo = CommitmentRepository(database.get_sync_session)

    with pytest.raises(IntegrityError):
        repo.create(CommitmentCreateInput(description="Bad state", state="INVALID"))

    with pytest.raises(IntegrityError):
        repo.create(CommitmentCreateInput(description="Bad importance", importance=10))

    with pytest.raises(IntegrityError):
        repo.create(CommitmentCreateInput(description="Bad effort", effort_provided=0))

    with pytest.raises(IntegrityError):
        repo.create(CommitmentCreateInput(description="Bad provenance", provenance_id=uuid4()))
