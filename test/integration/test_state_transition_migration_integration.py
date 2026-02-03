"""Integration tests for commitment state transition migrations and constraints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.state_transition_repository import (
    CommitmentStateTransitionCreateInput,
    CommitmentStateTransitionRepository,
    build_retention_cleanup_query,
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


def test_state_transition_constraints_enforced() -> None:
    """Database constraints reject invalid transition values."""
    _ensure_database_ready()
    database.run_migrations_sync()

    commitment_repo = CommitmentRepository(database.get_sync_session)
    transition_repo = CommitmentStateTransitionRepository(database.get_sync_session)
    commitment = commitment_repo.create(CommitmentCreateInput(description="Constraint test"))

    with pytest.raises(IntegrityError):
        transition_repo.create(
            CommitmentStateTransitionCreateInput(
                commitment_id=commitment.commitment_id,
                from_state="INVALID",
                to_state="OPEN",
                actor="user",
            )
        )

    with pytest.raises(IntegrityError):
        transition_repo.create(
            CommitmentStateTransitionCreateInput(
                commitment_id=commitment.commitment_id,
                from_state="OPEN",
                to_state="COMPLETED",
                actor="robot",
            )
        )

    with pytest.raises(IntegrityError):
        transition_repo.create(
            CommitmentStateTransitionCreateInput(
                commitment_id=commitment.commitment_id,
                from_state="OPEN",
                to_state="COMPLETED",
                actor="system",
                confidence=-0.5,
            )
        )

    commitment_repo.delete(commitment.commitment_id)


def test_transition_history_and_cascade_delete() -> None:
    """Transition history is ordered and cascades on commitment delete."""
    _ensure_database_ready()
    database.run_migrations_sync()

    commitment_repo = CommitmentRepository(database.get_sync_session)
    transition_repo = CommitmentStateTransitionRepository(database.get_sync_session)
    commitment = commitment_repo.create(CommitmentCreateInput(description="History test"))

    earlier = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    later = datetime(2025, 1, 2, 12, 0, 0, tzinfo=timezone.utc)

    transition_repo.create(
        CommitmentStateTransitionCreateInput(
            commitment_id=commitment.commitment_id,
            from_state="OPEN",
            to_state="MISSED",
            actor="system",
            transitioned_at=earlier,
        )
    )
    transition_repo.create(
        CommitmentStateTransitionCreateInput(
            commitment_id=commitment.commitment_id,
            from_state="MISSED",
            to_state="COMPLETED",
            actor="user",
            transitioned_at=later,
        )
    )

    history = transition_repo.list_for_commitment(commitment.commitment_id)
    assert [item.transitioned_at for item in history] == [later, earlier]

    commitment_repo.delete(commitment.commitment_id)
    assert transition_repo.list_for_commitment(commitment.commitment_id) == []


def test_retention_cleanup_sql_removes_old_records() -> None:
    """Retention cleanup SQL removes records older than the requested days."""
    _ensure_database_ready()
    database.run_migrations_sync()

    commitment_repo = CommitmentRepository(database.get_sync_session)
    transition_repo = CommitmentStateTransitionRepository(database.get_sync_session)
    commitment = commitment_repo.create(CommitmentCreateInput(description="Retention test"))

    now = datetime.now(timezone.utc)
    transition_repo.create(
        CommitmentStateTransitionCreateInput(
            commitment_id=commitment.commitment_id,
            from_state="OPEN",
            to_state="MISSED",
            actor="system",
            transitioned_at=now - timedelta(days=10),
        )
    )
    transition_repo.create(
        CommitmentStateTransitionCreateInput(
            commitment_id=commitment.commitment_id,
            from_state="MISSED",
            to_state="COMPLETED",
            actor="user",
            transitioned_at=now - timedelta(days=1),
        )
    )

    cleanup = build_retention_cleanup_query(5)
    with database.get_sync_session() as session:
        session.execute(cleanup, {"days": 5})
        session.commit()

    history = transition_repo.list_for_commitment(commitment.commitment_id)
    assert len(history) == 1
    assert history[0].to_state == "COMPLETED"

    commitment_repo.delete(commitment.commitment_id)
