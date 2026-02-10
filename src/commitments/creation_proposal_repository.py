"""Repository helpers for persisted commitment creation proposals."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping

from sqlalchemy.orm import Session

from models import CommitmentCreationProposal
from time_utils import to_utc


@dataclass(frozen=True)
class CommitmentCreationProposalCreateInput:
    """Input payload for creating or replacing a pending creation proposal."""

    proposal_ref: str
    proposal_kind: str
    payload: Mapping[str, object]
    source_channel: str
    source_actor: str | None = None
    proposed_at: datetime | None = None


class CommitmentCreationProposalRepository:
    """Repository for commitment creation proposal records."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize repository with a SQLAlchemy session factory."""
        self._session_factory = session_factory

    def create_or_replace_pending(
        self,
        payload: CommitmentCreationProposalCreateInput,
        *,
        now: datetime | None = None,
    ) -> CommitmentCreationProposal:
        """Create a pending proposal, replacing an existing record for the same reference."""
        timestamp = _normalize_timestamp(payload.proposed_at or now or datetime.now(timezone.utc))

        def handler(session: Session) -> CommitmentCreationProposal:
            existing = session.get(CommitmentCreationProposal, payload.proposal_ref)
            if existing is None:
                proposal = CommitmentCreationProposal(
                    proposal_ref=payload.proposal_ref,
                    proposal_kind=payload.proposal_kind,
                    status="pending",
                    payload=dict(payload.payload),
                    source_channel=payload.source_channel,
                    source_actor=payload.source_actor,
                    proposed_at=timestamp,
                )
                session.add(proposal)
                session.flush()
                return proposal

            existing.proposal_kind = payload.proposal_kind
            existing.status = "pending"
            existing.payload = dict(payload.payload)
            existing.source_channel = payload.source_channel
            existing.source_actor = payload.source_actor
            existing.proposed_at = timestamp
            existing.decided_at = None
            existing.decided_by = None
            existing.decision_reason = None
            existing.created_commitment_id = None
            session.flush()
            return existing

        return self._execute(handler)

    def get_pending(self, proposal_ref: str) -> CommitmentCreationProposal | None:
        """Return a pending proposal by its stable proposal_ref."""

        def handler(session: Session) -> CommitmentCreationProposal | None:
            proposal = session.get(CommitmentCreationProposal, proposal_ref)
            if proposal is None or proposal.status != "pending":
                return None
            return proposal

        return self._execute(handler)

    def mark_approved(
        self,
        proposal_ref: str,
        *,
        decided_by: str,
        created_commitment_id: int | None,
        decided_at: datetime | None = None,
        reason: str | None = None,
    ) -> CommitmentCreationProposal:
        """Mark a proposal approved and optionally attach the created commitment id."""

        def handler(session: Session) -> CommitmentCreationProposal:
            proposal = _require_proposal(session, proposal_ref)
            _apply_decision(
                proposal,
                status="approved",
                decided_by=decided_by,
                decided_at=decided_at,
                reason=reason,
                created_commitment_id=created_commitment_id,
            )
            session.flush()
            return proposal

        return self._execute(handler)

    def mark_rejected(
        self,
        proposal_ref: str,
        *,
        decided_by: str,
        decided_at: datetime | None = None,
        reason: str | None = None,
    ) -> CommitmentCreationProposal:
        """Mark a proposal rejected."""

        def handler(session: Session) -> CommitmentCreationProposal:
            proposal = _require_proposal(session, proposal_ref)
            _apply_decision(
                proposal,
                status="rejected",
                decided_by=decided_by,
                decided_at=decided_at,
                reason=reason,
                created_commitment_id=None,
            )
            session.flush()
            return proposal

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


def _require_proposal(session: Session, proposal_ref: str) -> CommitmentCreationProposal:
    """Load a proposal and fail fast when it does not exist."""
    proposal = session.get(CommitmentCreationProposal, proposal_ref)
    if proposal is None:
        raise ValueError(f"Creation proposal not found: {proposal_ref}")
    return proposal


def _apply_decision(
    proposal: CommitmentCreationProposal,
    *,
    status: str,
    decided_by: str,
    decided_at: datetime | None,
    reason: str | None,
    created_commitment_id: int | None,
) -> None:
    """Apply decision metadata to a proposal record."""
    proposal.status = status
    proposal.decided_by = decided_by
    proposal.decided_at = _normalize_timestamp(decided_at or datetime.now(timezone.utc))
    proposal.decision_reason = reason
    proposal.created_commitment_id = created_commitment_id


def _normalize_timestamp(value: datetime) -> datetime:
    """Normalize datetimes to UTC for persistence."""
    return to_utc(value)


__all__ = [
    "CommitmentCreationProposalCreateInput",
    "CommitmentCreationProposalRepository",
]
