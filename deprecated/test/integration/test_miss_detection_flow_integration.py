"""Integration tests for miss detection end-to-end flow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from attention.router import RoutingResult
from commitments.miss_detection import handle_miss_detection_callback
from commitments.miss_detection_scheduling import MissDetectionScheduleService
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from config import settings
from services import database
from test.helpers.scheduler_adapter_stub import RecordingSchedulerAdapter


class _StubRouter:
    """Stub attention router for miss detection integration tests."""

    async def route_envelope(self, envelope) -> RoutingResult:  # noqa: ANN001
        """Return a log-only routing result."""
        return RoutingResult(decision="LOG_ONLY", channel=None)


def _ensure_database_ready() -> None:
    """Skip tests when the integration database is not configured or reachable."""
    if not settings.database.url and not settings.database.postgres_password:
        pytest.skip("Integration DB not configured (set DATABASE_URL or POSTGRES_PASSWORD).")
    try:
        with database.get_sync_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Integration DB not reachable: {exc}")


def test_miss_detection_callback_transitions_commitment() -> None:
    """Miss detection callbacks should transition OPEN commitments to MISSED."""
    _ensure_database_ready()
    database.run_migrations_sync()

    repo = CommitmentRepository(database.get_sync_session)
    adapter = RecordingSchedulerAdapter()
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)
    schedule_service = MissDetectionScheduleService(
        database.get_sync_session,
        adapter,
        now_provider=lambda: now,
    )
    commitment = repo.create(CommitmentCreateInput(description="Integration miss", due_by=due_by))
    schedule_id = schedule_service.ensure_schedule(
        commitment_id=commitment.commitment_id,
        due_by=due_by,
    ).schedule_id
    assert schedule_id is not None

    result = handle_miss_detection_callback(
        database.get_sync_session,
        schedule_id=schedule_id,
        now=now + timedelta(hours=2),
        router=_StubRouter(),
    )

    assert result.status == "missed"
    refreshed = repo.get_by_id(commitment.commitment_id)
    assert refreshed is not None
    assert refreshed.state == "MISSED"
    assert refreshed.ever_missed_at is not None


def test_rescheduled_links_only_latest_triggers_miss() -> None:
    """Only the active schedule link should trigger miss detection."""
    _ensure_database_ready()
    database.run_migrations_sync()

    repo = CommitmentRepository(database.get_sync_session)
    adapter = RecordingSchedulerAdapter()
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)
    schedule_service = MissDetectionScheduleService(
        database.get_sync_session,
        adapter,
        now_provider=lambda: now,
    )
    commitment = repo.create(
        CommitmentCreateInput(description="Reschedule integration", due_by=due_by)
    )
    first_schedule = schedule_service.ensure_schedule(
        commitment_id=commitment.commitment_id,
        due_by=due_by,
    ).schedule_id
    assert first_schedule is not None

    updated_due_by = due_by + timedelta(hours=2)
    second_schedule = schedule_service.create_schedule(
        commitment_id=commitment.commitment_id,
        due_by=updated_due_by,
    ).schedule_id
    assert second_schedule is not None
    assert second_schedule != first_schedule

    old_result = handle_miss_detection_callback(
        database.get_sync_session,
        schedule_id=first_schedule,
        now=now + timedelta(hours=3),
        router=_StubRouter(),
    )
    assert old_result.status == "no_link"

    new_result = handle_miss_detection_callback(
        database.get_sync_session,
        schedule_id=second_schedule,
        now=now + timedelta(hours=3),
        router=_StubRouter(),
    )
    assert new_result.status == "missed"
