"""Unit tests for batch reminder delivery."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging

from sqlalchemy.orm import sessionmaker

from attention.router import RoutingResult
from commitments.batch_delivery import deliver_batch_reminder
from commitments.repository import CommitmentCreateInput, CommitmentRepository


@dataclass
class StubAttentionRouter:
    """Stub attention router capturing routed envelopes."""

    routed: list[object] = field(default_factory=list)

    async def route_envelope(self, envelope) -> RoutingResult:  # noqa: ANN001
        """Capture envelope and return a log-only result."""
        self.routed.append(envelope)
        return RoutingResult(decision="LOG_ONLY", channel=None)


def _create_commitment(factory: sessionmaker, *, description: str, now: datetime) -> int:
    """Create a commitment record for delivery tests."""
    repo = CommitmentRepository(factory)
    record = repo.create(
        CommitmentCreateInput(description=description),
        now=now,
    )
    return record.commitment_id


def _load_commitment(factory: sessionmaker, commitment_id: int):
    """Load a commitment record for assertions."""
    repo = CommitmentRepository(factory)
    record = repo.get_by_id(commitment_id)
    assert record is not None
    return record


def test_batch_delivery_submits_notification(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Non-empty batches should submit a BATCH notification."""
    router = StubAttentionRouter()
    now = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    first_id = _create_commitment(
        sqlite_session_factory,
        description="First task",
        now=now,
    )
    second_id = _create_commitment(
        sqlite_session_factory,
        description="Second task",
        now=now,
    )
    commitments = [
        _load_commitment(sqlite_session_factory, first_id),
        _load_commitment(sqlite_session_factory, second_id),
    ]
    message = "Daily reminders:\n- First task (due soon)"

    deliver_batch_reminder(
        router,
        commitments=commitments,
        message=message,
        owner="+15555550123",
        now=now,
    )

    assert len(router.routed) == 1
    envelope = router.routed[0]
    assert envelope.signal_type == "commitment.batch"
    assert envelope.channel_hint == "signal"
    assert envelope.signal_payload.message == message


def test_batch_delivery_skips_empty_batch(caplog) -> None:
    """Empty batches should not submit notifications and should log."""
    router = StubAttentionRouter()
    caplog.set_level(logging.INFO)

    result = deliver_batch_reminder(
        router,
        commitments=[],
        message="Daily reminders: none",
        owner="+15555550123",
        now=datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc),
    )

    assert result is None
    assert router.routed == []
    assert any("Batch reminder skipped" in record.message for record in caplog.records)
