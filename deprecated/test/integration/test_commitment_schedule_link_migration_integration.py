"""Integration tests for commitment schedule link migrations and repository."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.schedule_links import (
    CommitmentScheduleLinkCreateInput,
    CommitmentScheduleLinkRepository,
)
from config import settings
from models import Schedule, TaskIntent
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


def _create_schedule_id() -> int:
    """Create a schedule and return its ID."""
    now = datetime.now(timezone.utc)
    with database.get_sync_session() as session:
        intent = TaskIntent(
            summary="Commitment follow-up",
            details=None,
            creator_actor_type="system",
            creator_actor_id=None,
            creator_channel="tests",
            origin_reference=None,
            superseded_by_intent_id=None,
            created_at=now,
            updated_at=now,
        )
        session.add(intent)
        session.flush()
        schedule = Schedule(
            task_intent_id=intent.id,
            schedule_type="one_time",
            state="active",
            timezone="UTC",
            next_run_at=None,
            last_run_at=None,
            last_run_status=None,
            failure_count=0,
            last_execution_id=None,
            created_by_actor_type="system",
            created_by_actor_id=None,
            created_at=now,
            updated_at=now,
        )
        session.add(schedule)
        session.commit()
        return schedule.id


def test_create_link_and_resolve() -> None:
    """Creating a link allows resolving a commitment by schedule_id."""
    _ensure_database_ready()
    database.run_migrations_sync()

    commitment_repo = CommitmentRepository(database.get_sync_session)
    link_repo = CommitmentScheduleLinkRepository(database.get_sync_session)
    commitment = commitment_repo.create(CommitmentCreateInput(description="Integration link test"))
    schedule_id = _create_schedule_id()

    link_repo.create(
        CommitmentScheduleLinkCreateInput(
            commitment_id=commitment.commitment_id,
            schedule_id=schedule_id,
        )
    )

    resolved = link_repo.resolve_commitment_by_schedule_id(schedule_id)
    assert resolved is not None
    assert resolved.commitment_id == commitment.commitment_id

    commitment_repo.delete(commitment.commitment_id)


def test_resolve_inactive_link_returns_none() -> None:
    """Inactive links should not resolve."""
    _ensure_database_ready()
    database.run_migrations_sync()

    commitment_repo = CommitmentRepository(database.get_sync_session)
    link_repo = CommitmentScheduleLinkRepository(database.get_sync_session)
    commitment = commitment_repo.create(CommitmentCreateInput(description="Inactive link test"))
    schedule_id = _create_schedule_id()

    link_repo.create(
        CommitmentScheduleLinkCreateInput(
            commitment_id=commitment.commitment_id,
            schedule_id=schedule_id,
        )
    )
    link_repo.deactivate(commitment.commitment_id, schedule_id)

    assert link_repo.resolve_commitment_by_schedule_id(schedule_id) is None

    commitment_repo.delete(commitment.commitment_id)


def test_cascade_delete_removes_links() -> None:
    """Deleting a commitment cascades to delete schedule links."""
    _ensure_database_ready()
    database.run_migrations_sync()

    commitment_repo = CommitmentRepository(database.get_sync_session)
    link_repo = CommitmentScheduleLinkRepository(database.get_sync_session)
    commitment = commitment_repo.create(CommitmentCreateInput(description="Cascade link test"))
    schedule_id = _create_schedule_id()

    link_repo.create(
        CommitmentScheduleLinkCreateInput(
            commitment_id=commitment.commitment_id,
            schedule_id=schedule_id,
        )
    )

    commitment_repo.delete(commitment.commitment_id)

    assert link_repo.resolve_commitment_by_schedule_id(schedule_id) is None
