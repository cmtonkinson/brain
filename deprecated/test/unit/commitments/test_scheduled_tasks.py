"""Unit tests for commitment scheduled task handling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from attention.router import RoutingResult
from commitments.miss_detection_scheduling import MissDetectionScheduleService
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.scheduled_tasks import CommitmentScheduledTaskHandler
from models import Commitment, CommitmentReviewRun
from test.helpers.scheduler_adapter_stub import RecordingSchedulerAdapter


class StubAttentionRouter:
    """Stub attention router capturing routed envelopes."""

    def __init__(self) -> None:
        self.routed: list[object] = []

    async def route_envelope(self, envelope) -> RoutingResult:  # noqa: ANN001
        """Capture routed envelopes for inspection."""
        self.routed.append(envelope)
        return RoutingResult(decision="LOG_ONLY", channel=None)


def _create_commitment(
    factory: sessionmaker,
    *,
    description: str,
    due_by: datetime | None,
) -> Commitment:
    """Create and return a commitment record."""
    repo = CommitmentRepository(factory)
    return repo.create(CommitmentCreateInput(description=description, due_by=due_by))


def _create_miss_detection_schedule(
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


def test_commitment_miss_detection_runs(sqlite_session_factory: sessionmaker) -> None:
    """Miss detection scheduled tasks should transition OPEN commitments."""
    now = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)
    commitment = _create_commitment(
        sqlite_session_factory,
        description="Submit invoice",
        due_by=due_by,
    )
    schedule_id = _create_miss_detection_schedule(
        sqlite_session_factory,
        commitment.commitment_id,
        due_by,
        now=now,
    )
    router = StubAttentionRouter()
    handler = CommitmentScheduledTaskHandler(sqlite_session_factory, router)

    result = handler.handle(
        origin_reference=f"commitments.miss_detection:{commitment.commitment_id}",
        schedule_id=schedule_id,
        trace_id="trace-123",
        scheduled_for=now + timedelta(hours=2),
    )

    assert result is not None
    assert result.status == "success"
    refreshed = CommitmentRepository(sqlite_session_factory).get_by_id(commitment.commitment_id)
    assert refreshed is not None
    assert refreshed.state == "MISSED"


def test_commitment_daily_batch_delivers(sqlite_session_factory: sessionmaker) -> None:
    """Daily batch scheduled tasks should route reminders."""
    now = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
    _create_commitment(
        sqlite_session_factory,
        description="Call vendor",
        due_by=now + timedelta(hours=3),
    )
    router = StubAttentionRouter()
    handler = CommitmentScheduledTaskHandler(sqlite_session_factory, router)

    result = handler.handle(
        origin_reference="commitments.daily_batch",
        schedule_id=1,
        trace_id="trace-456",
        scheduled_for=now,
    )

    assert result is not None
    assert result.status == "success"
    assert len(router.routed) == 1
    envelope = router.routed[0]
    assert envelope.signal_type == "commitment.batch"


def test_commitment_weekly_review_delivers(sqlite_session_factory: sessionmaker) -> None:
    """Weekly review scheduled tasks should deliver summaries and record runs."""
    now = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
    commitment = _create_commitment(
        sqlite_session_factory,
        description="Review contract",
        due_by=None,
    )
    router = StubAttentionRouter()
    handler = CommitmentScheduledTaskHandler(sqlite_session_factory, router)

    result = handler.handle(
        origin_reference="commitments.weekly_review",
        schedule_id=2,
        trace_id="trace-789",
        scheduled_for=now,
    )

    assert result is not None
    assert result.status == "success"
    assert len(router.routed) == 1
    envelope = router.routed[0]
    assert envelope.signal_type == "commitment.review"
    with sqlite_session_factory() as session:
        review_runs = session.query(CommitmentReviewRun).all()
        assert len(review_runs) == 1
    refreshed = CommitmentRepository(sqlite_session_factory).get_by_id(commitment.commitment_id)
    assert refreshed is not None
    assert refreshed.presented_for_review_at is not None
