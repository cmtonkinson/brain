"""Unit tests for creation/dedupe proposal reply handling."""

from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from commitments.creation_proposal_repository import (
    CommitmentCreationProposalCreateInput,
    CommitmentCreationProposalRepository,
)
from commitments.proposal_reply_handler import CommitmentProposalReplyHandler
from commitments.repository import CommitmentCreateInput, CommitmentRepository
from test.helpers.scheduler_adapter_stub import RecordingSchedulerAdapter


def _create_pending_proposal(
    factory: sessionmaker,
    *,
    proposal_ref: str,
    proposal_kind: str,
    payload: dict,
) -> None:
    """Create a pending creation proposal record for reply handling tests."""
    CommitmentCreationProposalRepository(factory).create_or_replace_pending(
        CommitmentCreationProposalCreateInput(
            proposal_ref=proposal_ref,
            proposal_kind=proposal_kind,
            payload=payload,
            source_channel="signal",
            source_actor="+15550001111",
        )
    )


def test_handler_ignores_messages_without_proposal_ref(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Reply handling should no-op when no proposal reference is present."""
    handler = CommitmentProposalReplyHandler(sqlite_session_factory, RecordingSchedulerAdapter())

    assert handler.try_handle_reply("+15550001111", "yes") is None


def test_handler_rejects_proposal(sqlite_session_factory: sessionmaker) -> None:
    """Reject replies should mark proposals rejected without creating commitments."""
    proposal_ref = "signal:approval:abcdefabcdefabcd"
    _create_pending_proposal(
        sqlite_session_factory,
        proposal_ref=proposal_ref,
        proposal_kind="approval",
        payload={
            "creation_payload": {"description": "Maybe create this"},
            "authority": "user",
            "confidence": None,
            "source_context": None,
        },
    )

    handler = CommitmentProposalReplyHandler(sqlite_session_factory, RecordingSchedulerAdapter())
    result = handler.try_handle_reply("+15550001111", f"reject proposal_ref={proposal_ref}")

    assert result is not None
    assert result.status == "rejected"
    assert result.proposal_ref == proposal_ref
    assert (
        CommitmentCreationProposalRepository(sqlite_session_factory).get_pending(proposal_ref)
        is None
    )


def test_handler_approval_creates_commitment(sqlite_session_factory: sessionmaker) -> None:
    """Approval replies should create commitments for approval proposals."""
    proposal_ref = "signal:approval:1234567890abcdef"
    _create_pending_proposal(
        sqlite_session_factory,
        proposal_ref=proposal_ref,
        proposal_kind="approval",
        payload={
            "creation_payload": {"description": "Create from proposal"},
            "authority": "user",
            "confidence": None,
            "source_context": {
                "source_actor": "+15550001111",
                "source_medium": "message",
                "source_uri": None,
                "intake_channel": "signal",
            },
        },
    )

    handler = CommitmentProposalReplyHandler(sqlite_session_factory, RecordingSchedulerAdapter())
    result = handler.try_handle_reply("+15550001111", f"approve proposal_ref={proposal_ref}")

    assert result is not None
    assert result.status == "created"
    assert result.commitment_id is not None

    stored = CommitmentRepository(sqlite_session_factory).get_by_id(result.commitment_id)
    assert stored is not None
    assert stored.description == "Create from proposal"


def test_handler_dedupe_new_creates_with_bypass(sqlite_session_factory: sessionmaker) -> None:
    """Dedupe replies choosing new should bypass dedupe and create the commitment."""
    repo = CommitmentRepository(sqlite_session_factory)
    repo.create(CommitmentCreateInput(description="Schedule dentist visit"))

    proposal_ref = "signal:dedupe:fedcba0987654321"
    _create_pending_proposal(
        sqlite_session_factory,
        proposal_ref=proposal_ref,
        proposal_kind="dedupe",
        payload={
            "creation_payload": {"description": "Schedule dentist visit"},
            "authority": "user",
            "confidence": None,
            "source_context": None,
        },
    )

    handler = CommitmentProposalReplyHandler(sqlite_session_factory, RecordingSchedulerAdapter())
    result = handler.try_handle_reply("+15550001111", f"keep new proposal_ref={proposal_ref}")

    assert result is not None
    assert result.status == "created"
    assert result.commitment_id is not None
