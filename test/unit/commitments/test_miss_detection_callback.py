"""Unit tests for miss detection callback handling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from attention.router import RoutingResult
from commitments.miss_detection import handle_miss_detection_callback
from commitments.miss_detection_scheduling import MissDetectionScheduleService
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.transition_service import CommitmentStateTransitionService
from models import Commitment, CommitmentStateTransition
from test.helpers.scheduler_adapter_stub import RecordingSchedulerAdapter


def _create_commitment(
    factory: sessionmaker,
    *,
    description: str,
    due_by: datetime | None,
) -> Commitment:
    """Create and return a commitment record."""
    repo = CommitmentRepository(factory)
    return repo.create(CommitmentCreateInput(description=description, due_by=due_by))


def _create_schedule(
    factory: sessionmaker,
    commitment_id: int,
    due_by: datetime,
    *,
    now: datetime,
) -> int:
    """Create a miss detection schedule for the commitment."""
    adapter = RecordingSchedulerAdapter()
    service = MissDetectionScheduleService(factory, adapter, now_provider=lambda: now)
    result = service.ensure_schedule(commitment_id=commitment_id, due_by=due_by)
    assert result.schedule_id is not None
    return result.schedule_id


def _fetch_commitment(factory: sessionmaker, commitment_id: int) -> Commitment:
    """Fetch a commitment record by id."""
    repo = CommitmentRepository(factory)
    record = repo.get_by_id(commitment_id)
    assert record is not None
    return record


class _StubRouter:
    """Stub attention router for miss detection tests."""

    async def route_envelope(self, envelope) -> RoutingResult:  # noqa: ANN001
        """Return a log-only routing result."""
        return RoutingResult(decision="LOG_ONLY", channel=None)


def test_open_commitment_transitions_to_missed(
    sqlite_session_factory: sessionmaker,
) -> None:
    """OPEN commitments should transition to MISSED with audit metadata."""
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)
    commitment = _create_commitment(
        sqlite_session_factory,
        description="Pay invoice",
        due_by=due_by,
    )
    schedule_id = _create_schedule(
        sqlite_session_factory,
        commitment.commitment_id,
        due_by,
        now=now,
    )

    result = handle_miss_detection_callback(
        sqlite_session_factory,
        schedule_id=schedule_id,
        trace_id="trace-1",
        now=now + timedelta(hours=2),
        router=_StubRouter(),
    )

    assert result.status == "missed"
    refreshed = _fetch_commitment(sqlite_session_factory, commitment.commitment_id)
    assert refreshed.state == "MISSED"
    assert refreshed.ever_missed_at is not None
    with sqlite_session_factory() as session:
        transition = (
            session.query(CommitmentStateTransition)
            .filter(
                CommitmentStateTransition.commitment_id == commitment.commitment_id,
                CommitmentStateTransition.to_state == "MISSED",
            )
            .order_by(CommitmentStateTransition.transition_id.desc())
            .first()
        )
        assert transition is not None
        assert transition.from_state == "OPEN"
        assert transition.actor == "system"
        assert transition.reason == "due_by_expired"


def test_ever_missed_at_not_overwritten(sqlite_session_factory: sessionmaker) -> None:
    """ever_missed_at should be set only on first MISSED transition."""
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)
    commitment = _create_commitment(
        sqlite_session_factory,
        description="Send report",
        due_by=due_by,
    )
    schedule_id = _create_schedule(
        sqlite_session_factory,
        commitment.commitment_id,
        due_by,
        now=now,
    )

    handle_miss_detection_callback(
        sqlite_session_factory,
        schedule_id=schedule_id,
        now=now + timedelta(hours=2),
        router=_StubRouter(),
    )
    first = _fetch_commitment(sqlite_session_factory, commitment.commitment_id).ever_missed_at

    handle_miss_detection_callback(
        sqlite_session_factory,
        schedule_id=schedule_id,
        now=now + timedelta(hours=3),
        router=_StubRouter(),
    )
    second = _fetch_commitment(sqlite_session_factory, commitment.commitment_id).ever_missed_at

    assert first == second


@pytest.mark.parametrize("state", ["COMPLETED", "CANCELED", "MISSED"])
def test_non_open_states_noop(
    sqlite_session_factory: sessionmaker,
    state: str,
) -> None:
    """Non-OPEN commitments should not transition again."""
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)
    commitment = _create_commitment(
        sqlite_session_factory,
        description=f"State {state}",
        due_by=due_by,
    )
    schedule_id = _create_schedule(
        sqlite_session_factory,
        commitment.commitment_id,
        due_by,
        now=now,
    )
    transition_service = CommitmentStateTransitionService(sqlite_session_factory)
    actor = "system" if state == "MISSED" else "user"
    transition_service.transition(
        commitment_id=commitment.commitment_id,
        to_state=state,
        actor=actor,
        reason="test_setup",
        now=now,
    )

    result = handle_miss_detection_callback(
        sqlite_session_factory,
        schedule_id=schedule_id,
        now=now + timedelta(hours=2),
        router=_StubRouter(),
    )

    assert result.status == "noop"
    refreshed = _fetch_commitment(sqlite_session_factory, commitment.commitment_id)
    assert refreshed.state == state


def test_missing_schedule_link_noops(sqlite_session_factory: sessionmaker) -> None:
    """Missing schedule links should result in a no-link outcome."""
    result = handle_miss_detection_callback(
        sqlite_session_factory,
        schedule_id=9999,
        trace_id="trace-missing",
        now=datetime.now(timezone.utc),
        router=_StubRouter(),
    )

    assert result.status == "no_link"
