"""Unit tests for missed commitment notification triggering."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from attention.router import RoutingResult
from commitments.notifications import (
    normalize_urgency_priority,
    submit_missed_commitment_notification,
)
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.transition_service import CommitmentStateTransitionService
from models import Commitment


@dataclass
class StubAttentionRouter:
    """Stub attention router capturing routing envelopes."""

    routed: list[object] = field(default_factory=list)

    async def route_envelope(self, envelope) -> RoutingResult:  # noqa: ANN001
        """Capture envelope and return a log-only result."""
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
    record = repo.create(CommitmentCreateInput(description=description, due_by=due_by))
    return record


def test_missed_transition_triggers_notification(sqlite_session_factory: sessionmaker) -> None:
    """MISSED transitions should submit notifications with correct content."""
    router = StubAttentionRouter()
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)
    commitment = _create_commitment(
        sqlite_session_factory,
        description="Send summary",
        due_by=due_by,
    )
    transition_service = CommitmentStateTransitionService(
        sqlite_session_factory,
        on_missed_hook=lambda record: submit_missed_commitment_notification(router, record),
    )

    transition_service.transition(
        commitment_id=commitment.commitment_id,
        to_state="MISSED",
        actor="system",
        reason="due_by_expired",
        now=now + timedelta(hours=2),
    )

    assert len(router.routed) == 1
    envelope = router.routed[0]
    assert envelope.signal_type == "commitment.missed"
    assert str(commitment.commitment_id) in envelope.notification.origin_signal
    assert "Send summary" in envelope.signal_payload.message
    assert "due by" in envelope.signal_payload.message.lower()
    expected_priority = normalize_urgency_priority(commitment.urgency)
    assert envelope.urgency == expected_priority


def test_notification_failure_does_not_block_transition(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Notification failures should not rollback MISSED transitions."""
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    commitment = _create_commitment(
        sqlite_session_factory,
        description="Fail notification",
        due_by=now + timedelta(hours=1),
    )

    def _fail_hook(_: Commitment) -> None:
        raise RuntimeError("boom")

    transition_service = CommitmentStateTransitionService(
        sqlite_session_factory,
        on_missed_hook=_fail_hook,
    )
    transition_service.transition(
        commitment_id=commitment.commitment_id,
        to_state="MISSED",
        actor="system",
        reason="due_by_expired",
        now=now + timedelta(hours=2),
    )

    refreshed = CommitmentRepository(sqlite_session_factory).get_by_id(commitment.commitment_id)
    assert refreshed is not None
    assert refreshed.state == "MISSED"
