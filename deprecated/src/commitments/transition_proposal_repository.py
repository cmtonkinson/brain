"""Repository helpers for commitment transition proposal persistence."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from models import CommitmentTransitionProposal
from time_utils import to_utc


@dataclass(frozen=True)
class CommitmentTransitionProposalCreateInput:
    """Input payload for creating a commitment transition proposal."""

    commitment_id: int
    from_state: str
    to_state: str
    actor: str
    threshold: float
    confidence: float | None = None
    reason: str | None = None
    context: Mapping[str, object] | None = None
    provenance_id: UUID | None = None
    proposed_at: datetime | None = None


class CommitmentTransitionProposalRepository:
    """Repository for commitment transition proposal records."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize repository with a SQLAlchemy session factory."""
        self._session_factory = session_factory

    def create(
        self,
        payload: CommitmentTransitionProposalCreateInput,
        *,
        now: datetime | None = None,
    ) -> CommitmentTransitionProposal:
        """Create and persist a transition proposal record."""

        def handler(session: Session) -> CommitmentTransitionProposal:
            return create_transition_proposal_record(session, payload, now=now)

        return self._execute(handler)

    def get_pending_for_commitment(self, commitment_id: int) -> CommitmentTransitionProposal | None:
        """Return the most recent pending proposal for a commitment."""

        def handler(session: Session) -> CommitmentTransitionProposal | None:
            return (
                session.query(CommitmentTransitionProposal)
                .filter(
                    CommitmentTransitionProposal.commitment_id == commitment_id,
                    CommitmentTransitionProposal.status == "pending",
                )
                .order_by(
                    CommitmentTransitionProposal.proposed_at.desc(),
                    CommitmentTransitionProposal.proposal_id.desc(),
                )
                .first()
            )

        return self._execute(handler)

    def mark_approved(
        self,
        proposal_id: int,
        *,
        decided_by: str,
        decided_at: datetime | None = None,
        reason: str | None = None,
    ) -> CommitmentTransitionProposal:
        """Mark a proposal as approved and return the updated record."""

        def handler(session: Session) -> CommitmentTransitionProposal:
            proposal = session.get(CommitmentTransitionProposal, proposal_id)
            if proposal is None:
                raise ValueError(f"Transition proposal not found: {proposal_id}")
            _apply_decision(
                proposal,
                status="approved",
                decided_by=decided_by,
                decided_at=decided_at,
                reason=reason,
            )
            session.flush()
            return proposal

        return self._execute(handler)

    def mark_rejected(
        self,
        proposal_id: int,
        *,
        decided_by: str,
        decided_at: datetime | None = None,
        reason: str | None = None,
    ) -> CommitmentTransitionProposal:
        """Mark a proposal as rejected and return the updated record."""

        def handler(session: Session) -> CommitmentTransitionProposal:
            proposal = session.get(CommitmentTransitionProposal, proposal_id)
            if proposal is None:
                raise ValueError(f"Transition proposal not found: {proposal_id}")
            _apply_decision(
                proposal,
                status="rejected",
                decided_by=decided_by,
                decided_at=decided_at,
                reason=reason,
            )
            session.flush()
            return proposal

        return self._execute(handler)

    def cancel_pending_for_commitment(
        self,
        commitment_id: int,
        *,
        decided_by: str,
        decided_at: datetime | None = None,
        reason: str | None = None,
    ) -> int:
        """Cancel any pending proposals for a commitment and return count."""

        def handler(session: Session) -> int:
            return cancel_pending_proposals(
                session,
                commitment_id=commitment_id,
                decided_by=decided_by,
                decided_at=decided_at,
                reason=reason,
            )

        return self._execute(handler)

    def _execute(self, handler):
        """Execute repository work inside a managed session."""
        with closing(self._session_factory()) as session:
            session.expire_on_commit = False
            try:
                result = handler(session)
                session.commit()
            except Exception:
                session.rollback()
                raise
        return result


def create_transition_proposal_record(
    session: Session,
    payload: CommitmentTransitionProposalCreateInput,
    *,
    now: datetime | None = None,
) -> CommitmentTransitionProposal:
    """Create a transition proposal using an existing session."""
    proposed_at = _normalize_timestamp(payload.proposed_at or now or datetime.now(timezone.utc))
    proposal = CommitmentTransitionProposal(
        commitment_id=payload.commitment_id,
        from_state=payload.from_state,
        to_state=payload.to_state,
        actor=payload.actor,
        confidence=payload.confidence,
        threshold=payload.threshold,
        reason=payload.reason,
        context=dict(payload.context) if payload.context is not None else None,
        proposed_at=proposed_at,
        status="pending",
        provenance_id=payload.provenance_id,
    )
    session.add(proposal)
    session.flush()
    return proposal


def cancel_pending_proposals(
    session: Session,
    *,
    commitment_id: int,
    decided_by: str,
    decided_at: datetime | None = None,
    reason: str | None = None,
) -> int:
    """Cancel pending proposals for a commitment and return count."""
    resolved_at = _normalize_timestamp(decided_at or datetime.now(timezone.utc))
    updated = (
        session.query(CommitmentTransitionProposal)
        .filter(
            CommitmentTransitionProposal.commitment_id == commitment_id,
            CommitmentTransitionProposal.status == "pending",
        )
        .update(
            {
                "status": "canceled",
                "decided_at": resolved_at,
                "decided_by": decided_by,
                "decision_reason": reason,
            },
            synchronize_session=False,
        )
    )
    session.flush()
    return int(updated or 0)


def _apply_decision(
    proposal: CommitmentTransitionProposal,
    *,
    status: str,
    decided_by: str,
    decided_at: datetime | None,
    reason: str | None,
) -> None:
    """Update proposal status fields for a decision."""
    proposal.status = status
    proposal.decided_by = decided_by
    proposal.decided_at = _normalize_timestamp(decided_at or datetime.now(timezone.utc))
    proposal.decision_reason = reason


def _normalize_timestamp(value: datetime) -> datetime:
    """Normalize a datetime value to UTC."""
    return to_utc(value)


__all__ = [
    "CommitmentTransitionProposalCreateInput",
    "CommitmentTransitionProposalRepository",
    "cancel_pending_proposals",
    "create_transition_proposal_record",
]
