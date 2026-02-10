"""Unit tests for creation proposal repository persistence behavior."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from commitments.creation_proposal_repository import (
    CommitmentCreationProposalCreateInput,
    CommitmentCreationProposalRepository,
)


def test_create_and_get_pending(sqlite_session_factory: sessionmaker) -> None:
    """Pending proposals should be retrievable by proposal_ref."""
    repo = CommitmentCreationProposalRepository(sqlite_session_factory)

    created = repo.create_or_replace_pending(
        CommitmentCreationProposalCreateInput(
            proposal_ref="ingest:approval:1234567890abcdef",
            proposal_kind="approval",
            payload={"creation_payload": {"description": "Draft proposal"}},
            source_channel="signal",
            source_actor="+15550001111",
            proposed_at=datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc),
        )
    )
    pending = repo.get_pending(created.proposal_ref)

    assert pending is not None
    assert pending.proposal_ref == created.proposal_ref
    assert pending.status == "pending"


def test_mark_approved_sets_decision_fields(sqlite_session_factory: sessionmaker) -> None:
    """Approvals should persist decision metadata and created commitment linkage."""
    repo = CommitmentCreationProposalRepository(sqlite_session_factory)
    proposal_ref = "ingest:approval:abcdefabcdefabcd"
    repo.create_or_replace_pending(
        CommitmentCreationProposalCreateInput(
            proposal_ref=proposal_ref,
            proposal_kind="approval",
            payload={"creation_payload": {"description": "Approve me"}},
            source_channel="signal",
        )
    )

    updated = repo.mark_approved(
        proposal_ref,
        decided_by="+15550002222",
        created_commitment_id=42,
        reason="operator_approved",
    )

    assert updated.status == "approved"
    assert updated.decided_by == "+15550002222"
    assert updated.created_commitment_id == 42
    assert updated.decision_reason == "operator_approved"
    assert repo.get_pending(proposal_ref) is None


def test_mark_rejected_sets_decision_fields(sqlite_session_factory: sessionmaker) -> None:
    """Rejections should persist decision metadata and clear pending lookup."""
    repo = CommitmentCreationProposalRepository(sqlite_session_factory)
    proposal_ref = "ingest:dedupe:abcdefabcdefabcd"
    repo.create_or_replace_pending(
        CommitmentCreationProposalCreateInput(
            proposal_ref=proposal_ref,
            proposal_kind="dedupe",
            payload={"creation_payload": {"description": "Duplicate"}},
            source_channel="signal",
        )
    )

    updated = repo.mark_rejected(
        proposal_ref,
        decided_by="+15550003333",
        reason="operator_rejected",
    )

    assert updated.status == "rejected"
    assert updated.decided_by == "+15550003333"
    assert updated.decision_reason == "operator_rejected"
    assert repo.get_pending(proposal_ref) is None
