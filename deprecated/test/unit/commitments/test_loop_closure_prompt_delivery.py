"""Unit tests for loop-closure prompt delivery."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from attention.router import RoutingResult
from commitments.loop_closure_prompts import generate_loop_closure_prompt
from commitments.notifications import submit_loop_closure_prompt_notification
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


def test_due_by_commitment_triggers_prompt_delivery(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Commitments with due_by should trigger loop-closure prompt delivery."""
    router = StubAttentionRouter()
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)
    commitment = _create_commitment(
        sqlite_session_factory,
        description="Follow up with client",
        due_by=due_by,
    )

    submit_loop_closure_prompt_notification(router, commitment)

    assert len(router.routed) == 1
    envelope = router.routed[0]
    assert envelope.signal_type == "commitment.loop_closure"
    expected = generate_loop_closure_prompt(
        description=commitment.description,
        due_by=commitment.due_by,
    )
    assert envelope.signal_payload.message == expected


def test_no_due_by_no_prompt_delivery(sqlite_session_factory: sessionmaker) -> None:
    """Commitments without due_by should not trigger prompt delivery."""
    router = StubAttentionRouter()
    commitment = _create_commitment(
        sqlite_session_factory,
        description="Undated commitment",
        due_by=None,
    )

    result = submit_loop_closure_prompt_notification(router, commitment)

    assert result is None
    assert router.routed == []


def test_prompt_failure_does_not_block_transition(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Prompt delivery failures should not rollback MISSED transitions."""
    now = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    commitment = _create_commitment(
        sqlite_session_factory,
        description="Prompt failure",
        due_by=now + timedelta(hours=1),
    )

    def _fail_hook(_: Commitment) -> None:
        raise RuntimeError("prompt failure")

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
