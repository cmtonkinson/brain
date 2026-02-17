"""Unit tests for loop-closure reply detection and handling."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from commitments.loop_closure_actions import LoopClosureActionResult
from commitments.loop_closure_handler import (
    LoopClosureReplyHandler,
    detect_loop_closure_reply,
)
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.transition_service import CommitmentStateTransitionService
from test.helpers.scheduler_adapter_stub import RecordingSchedulerAdapter


def _create_commitment(
    factory: sessionmaker,
    *,
    description: str,
    now: datetime,
) -> int:
    """Create a commitment and return its ID."""
    record = CommitmentRepository(factory).create(
        CommitmentCreateInput(description=description),
        now=now,
    )
    return record.commitment_id


def _mark_completed(
    factory: sessionmaker,
    *,
    commitment_id: int,
    now: datetime,
) -> None:
    """Transition a commitment into COMPLETED state."""
    CommitmentStateTransitionService(factory).transition(
        commitment_id=commitment_id,
        to_state="COMPLETED",
        actor="user",
        reason="test_setup_completed",
        now=now,
    )


def test_detect_uses_signal_reference_over_fallback(sqlite_session_factory: sessionmaker) -> None:
    """Signal reference should deterministically select the target commitment."""
    earlier = datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc)
    later = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)
    referenced_id = _create_commitment(
        sqlite_session_factory,
        description="Referenced commitment",
        now=earlier,
    )
    _create_commitment(
        sqlite_session_factory,
        description="Most recent unresolved commitment",
        now=later,
    )

    with sqlite_session_factory() as session:
        context = detect_loop_closure_reply(
            session,
            sender="+15550001111",
            message="done",
            signal_reference=f"commitment.missed:{referenced_id}",
        )

    assert context is not None
    assert context.commitment_id == referenced_id


def test_detect_uses_reference_embedded_in_message(sqlite_session_factory: sessionmaker) -> None:
    """Message references should select the referenced commitment when present."""
    referenced_id = _create_commitment(
        sqlite_session_factory,
        description="Embedded reference",
        now=datetime(2026, 2, 2, 9, 0, tzinfo=timezone.utc),
    )
    _create_commitment(
        sqlite_session_factory,
        description="Unrelated unresolved commitment",
        now=datetime(2026, 2, 2, 10, 0, tzinfo=timezone.utc),
    )

    with sqlite_session_factory() as session:
        context = detect_loop_closure_reply(
            session,
            sender="+15550001111",
            message=f"complete commitment.missed:{referenced_id}",
        )

    assert context is not None
    assert context.commitment_id == referenced_id


def test_detect_falls_back_to_latest_unresolved(sqlite_session_factory: sessionmaker) -> None:
    """When no reference exists, resolver should pick the latest unresolved commitment."""
    older_id = _create_commitment(
        sqlite_session_factory,
        description="Older unresolved commitment",
        now=datetime(2026, 2, 3, 9, 0, tzinfo=timezone.utc),
    )
    newer_id = _create_commitment(
        sqlite_session_factory,
        description="Newer unresolved commitment",
        now=datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc),
    )
    resolved_id = _create_commitment(
        sqlite_session_factory,
        description="Resolved commitment",
        now=datetime(2026, 2, 3, 11, 0, tzinfo=timezone.utc),
    )
    _mark_completed(
        sqlite_session_factory,
        commitment_id=resolved_id,
        now=datetime(2026, 2, 3, 11, 5, tzinfo=timezone.utc),
    )

    with sqlite_session_factory() as session:
        context = detect_loop_closure_reply(
            session,
            sender="+15550001111",
            message="done",
        )

    assert context is not None
    assert context.commitment_id == newer_id
    assert context.commitment_id != older_id


def test_detect_returns_none_without_unresolved_commitments(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Loop-closure replies should be ignored when no unresolved commitments exist."""
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Only resolved commitment",
        now=datetime(2026, 2, 4, 9, 0, tzinfo=timezone.utc),
    )
    _mark_completed(
        sqlite_session_factory,
        commitment_id=commitment_id,
        now=datetime(2026, 2, 4, 9, 5, tzinfo=timezone.utc),
    )

    with sqlite_session_factory() as session:
        context = detect_loop_closure_reply(
            session,
            sender="+15550001111",
            message="done",
        )

    assert context is None


def test_try_handle_reply_resolves_reference_and_applies_action(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Handler should pass the resolved commitment ID to the action service."""
    commitment_id = _create_commitment(
        sqlite_session_factory,
        description="Handler target",
        now=datetime(2026, 2, 5, 9, 0, tzinfo=timezone.utc),
    )
    handler = LoopClosureReplyHandler(
        sqlite_session_factory,
        RecordingSchedulerAdapter(),
    )

    class _ActionServiceStub:
        """Stub action service for loop-closure reply handling tests."""

        def __init__(self) -> None:
            self.last_request = None

        def apply_intent(self, request):  # noqa: ANN001
            """Capture the request and return a successful result."""
            self.last_request = request
            return LoopClosureActionResult(
                status="completed",
                commitment_id=request.commitment_id,
                prior_state="MISSED",
                new_state="COMPLETED",
            )

    stub = _ActionServiceStub()
    handler._action_service = stub

    result = handler.try_handle_reply(
        sender="+15550001111",
        message="done",
        timestamp=datetime(2026, 2, 5, 9, 30, tzinfo=timezone.utc),
        signal_reference=f"commitment.missed:{commitment_id}",
    )

    assert result is not None
    assert result.status == "completed"
    assert stub.last_request is not None
    assert stub.last_request.commitment_id == commitment_id
