"""Unit tests for commitment state transition service behavior."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from commitments.repository import (
    CommitmentCreateInput,
    CommitmentRepository,
    CommitmentUpdateInput,
)
from commitments.state_transition_repository import CommitmentStateTransitionRepository
from commitments.transition_proposal_repository import (
    CommitmentTransitionProposalCreateInput,
    CommitmentTransitionProposalRepository,
)
from commitments.transition_service import CommitmentStateTransitionService


def test_transition_updates_state_and_creates_audit(sqlite_session_factory: sessionmaker) -> None:
    """Successful transitions should update state and create audit records."""
    repo = CommitmentRepository(sqlite_session_factory)
    commitment = repo.create(CommitmentCreateInput(description="Ship release"))
    service = CommitmentStateTransitionService(sqlite_session_factory)

    transition = service.transition(
        commitment_id=commitment.commitment_id,
        to_state="COMPLETED",
        actor="user",
        reason="done",
        context={"source": "unit"},
        confidence=1.0,
        now=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    updated = repo.get_by_id(commitment.commitment_id)
    assert updated is not None
    assert updated.state == "COMPLETED"

    assert transition.from_state == "OPEN"
    assert transition.to_state == "COMPLETED"
    assert transition.actor == "user"

    transitions = CommitmentStateTransitionRepository(sqlite_session_factory).list_for_commitment(
        commitment.commitment_id
    )
    assert len(transitions) == 1


def test_transition_rollback_on_audit_failure(sqlite_session_factory: sessionmaker) -> None:
    """Audit insert failures should rollback commitment state changes."""
    repo = CommitmentRepository(sqlite_session_factory)
    commitment = repo.create(CommitmentCreateInput(description="Rollback test"))
    service = CommitmentStateTransitionService(sqlite_session_factory)

    with pytest.raises(IntegrityError):
        service.transition(
            commitment_id=commitment.commitment_id,
            to_state="INVALID",
            actor="user",
        )

    refreshed = repo.get_by_id(commitment.commitment_id)
    assert refreshed is not None
    assert refreshed.state == "OPEN"

    transitions = CommitmentStateTransitionRepository(sqlite_session_factory).list_for_commitment(
        commitment.commitment_id
    )
    assert transitions == []


def test_transition_invalid_commitment_id_raises(sqlite_session_factory: sessionmaker) -> None:
    """Missing commitments should raise errors and not create audit records."""
    service = CommitmentStateTransitionService(sqlite_session_factory)

    with pytest.raises(ValueError):
        service.transition(commitment_id=9999, to_state="COMPLETED", actor="user")


def test_direct_state_update_is_rejected(sqlite_session_factory: sessionmaker) -> None:
    """Direct repository updates that change state should be rejected."""
    repo = CommitmentRepository(sqlite_session_factory)
    commitment = repo.create(CommitmentCreateInput(description="Guard test"))

    with pytest.raises(ValueError):
        repo.update(
            commitment.commitment_id,
            CommitmentUpdateInput(state="COMPLETED"),
        )


def test_multiple_transitions_record_sequence(sqlite_session_factory: sessionmaker) -> None:
    """Multiple transitions should create multiple audit records in order."""
    repo = CommitmentRepository(sqlite_session_factory)
    commitment = repo.create(CommitmentCreateInput(description="Sequence test"))
    service = CommitmentStateTransitionService(sqlite_session_factory)

    service.transition(
        commitment_id=commitment.commitment_id,
        to_state="COMPLETED",
        actor="user",
    )
    service.transition(
        commitment_id=commitment.commitment_id,
        to_state="CANCELED",
        actor="user",
    )

    transitions = CommitmentStateTransitionRepository(sqlite_session_factory).list_for_commitment(
        commitment.commitment_id
    )
    assert len(transitions) == 2
    assert transitions[0].from_state == "COMPLETED"
    assert transitions[0].to_state == "CANCELED"
    assert transitions[1].from_state == "OPEN"
    assert transitions[1].to_state == "COMPLETED"


def test_transition_completion_hook_invoked(sqlite_session_factory: sessionmaker) -> None:
    """Completion hook should run for COMPLETED/CANCELED transitions."""
    repo = CommitmentRepository(sqlite_session_factory)
    commitment = repo.create(CommitmentCreateInput(description="Hook test"))
    called: list[int] = []

    def _hook(commitment_id: int) -> None:
        called.append(commitment_id)

    service = CommitmentStateTransitionService(
        sqlite_session_factory,
        on_completion_hook=_hook,
    )

    service.transition(
        commitment_id=commitment.commitment_id,
        to_state="COMPLETED",
        actor="user",
    )

    assert called == [commitment.commitment_id]


def test_transition_returns_proposal_without_confidence(
    sqlite_session_factory: sessionmaker,
) -> None:
    """System transitions without confidence should return a proposal."""
    repo = CommitmentRepository(sqlite_session_factory)
    commitment = repo.create(CommitmentCreateInput(description="Needs confidence"))
    service = CommitmentStateTransitionService(sqlite_session_factory)

    proposal = service.transition(
        commitment_id=commitment.commitment_id,
        to_state="COMPLETED",
        actor="system",
    )

    refreshed = repo.get_by_id(commitment.commitment_id)
    assert refreshed is not None
    assert refreshed.state == "OPEN"

    transitions = CommitmentStateTransitionRepository(sqlite_session_factory).list_for_commitment(
        commitment.commitment_id
    )
    assert transitions == []

    pending = CommitmentTransitionProposalRepository(
        sqlite_session_factory
    ).get_pending_for_commitment(commitment.commitment_id)
    assert pending is not None
    assert pending.proposal_id == proposal.proposal_id
    assert pending.to_state == "COMPLETED"


def test_missed_transition_allows_without_confidence(sqlite_session_factory: sessionmaker) -> None:
    """System MISSED transitions should be allowed without confidence."""
    repo = CommitmentRepository(sqlite_session_factory)
    commitment = repo.create(CommitmentCreateInput(description="Missed allowed"))
    service = CommitmentStateTransitionService(sqlite_session_factory)

    transition = service.transition(
        commitment_id=commitment.commitment_id,
        to_state="MISSED",
        actor="system",
    )

    assert transition.to_state == "MISSED"


def test_user_transition_cancels_pending_proposals(sqlite_session_factory: sessionmaker) -> None:
    """User transitions should cancel any pending proposals."""
    repo = CommitmentRepository(sqlite_session_factory)
    commitment = repo.create(CommitmentCreateInput(description="Cancel pending"))
    proposal_repo = CommitmentTransitionProposalRepository(sqlite_session_factory)
    proposal_repo.create(
        CommitmentTransitionProposalCreateInput(
            commitment_id=commitment.commitment_id,
            from_state="OPEN",
            to_state="COMPLETED",
            actor="system",
            confidence=0.2,
            threshold=0.9,
            reason="unit_test",
        )
    )
    service = CommitmentStateTransitionService(sqlite_session_factory)

    service.transition(
        commitment_id=commitment.commitment_id,
        to_state="CANCELED",
        actor="user",
    )

    pending = proposal_repo.get_pending_for_commitment(commitment.commitment_id)
    assert pending is None
