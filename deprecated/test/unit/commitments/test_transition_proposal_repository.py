"""Unit tests for commitment transition proposal repository."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from commitments.repository import CommitmentCreateInput, CommitmentRepository
from commitments.transition_proposal_repository import (
    CommitmentTransitionProposalCreateInput,
    CommitmentTransitionProposalRepository,
)


def test_create_and_fetch_pending(sqlite_session_factory: sessionmaker) -> None:
    """Pending proposals should be retrievable after creation."""
    commitment = CommitmentRepository(sqlite_session_factory).create(
        CommitmentCreateInput(description="Proposal pending")
    )
    repo = CommitmentTransitionProposalRepository(sqlite_session_factory)
    proposal = repo.create(
        CommitmentTransitionProposalCreateInput(
            commitment_id=commitment.commitment_id,
            from_state="OPEN",
            to_state="COMPLETED",
            actor="system",
            confidence=0.2,
            threshold=0.9,
            reason="unit",
        )
    )

    pending = repo.get_pending_for_commitment(commitment.commitment_id)
    assert pending is not None
    assert pending.proposal_id == proposal.proposal_id
    assert pending.status == "pending"


def test_mark_approved_sets_decision_fields(sqlite_session_factory: sessionmaker) -> None:
    """Approving a proposal should set decision metadata."""
    commitment = CommitmentRepository(sqlite_session_factory).create(
        CommitmentCreateInput(description="Proposal approve")
    )
    repo = CommitmentTransitionProposalRepository(sqlite_session_factory)
    proposal = repo.create(
        CommitmentTransitionProposalCreateInput(
            commitment_id=commitment.commitment_id,
            from_state="OPEN",
            to_state="CANCELED",
            actor="system",
            confidence=0.1,
            threshold=0.9,
            reason="unit",
        )
    )
    decided_at = datetime(2026, 2, 5, 12, 0, tzinfo=timezone.utc)

    updated = repo.mark_approved(
        proposal.proposal_id,
        decided_by="user",
        decided_at=decided_at,
        reason="confirmed",
    )

    assert updated.status == "approved"
    assert updated.decided_by == "user"
    assert updated.decided_at == decided_at
    assert updated.decision_reason == "confirmed"


def test_cancel_pending_for_commitment(sqlite_session_factory: sessionmaker) -> None:
    """Canceling pending proposals should update status."""
    commitment = CommitmentRepository(sqlite_session_factory).create(
        CommitmentCreateInput(description="Proposal cancel")
    )
    repo = CommitmentTransitionProposalRepository(sqlite_session_factory)
    repo.create(
        CommitmentTransitionProposalCreateInput(
            commitment_id=commitment.commitment_id,
            from_state="OPEN",
            to_state="COMPLETED",
            actor="system",
            confidence=0.3,
            threshold=0.9,
            reason="unit",
        )
    )

    count = repo.cancel_pending_for_commitment(
        commitment.commitment_id,
        decided_by="user",
        reason="override",
    )

    assert count == 1
    assert repo.get_pending_for_commitment(commitment.commitment_id) is None
