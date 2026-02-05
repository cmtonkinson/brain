"""Atomic commitment state transition service with audit logging."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import logging
from typing import Callable, Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from commitments.repository import CommitmentUpdateInput, _apply_updates, _fetch_commitment
from commitments.state_transition_repository import (
    CommitmentStateTransitionCreateInput,
    create_transition_record,
)
from commitments.transition_proposal_repository import (
    CommitmentTransitionProposalCreateInput,
    cancel_pending_proposals,
    create_transition_proposal_record,
)
from commitments.transition_authority import evaluate_transition_authority
from models import Commitment, CommitmentStateTransition, CommitmentTransitionProposal
from time_utils import to_utc

logger = logging.getLogger(__name__)


class CommitmentStateTransitionService:
    """Service for atomically updating commitment state and audit records."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        on_completion_hook: Callable[[int], None] | None = None,
        on_missed_hook: Callable[[Commitment], None] | None = None,
        on_proposal_hook: Callable[[CommitmentTransitionProposal], None] | None = None,
    ) -> None:
        """Initialize the service with a SQLAlchemy session factory."""
        self._session_factory = session_factory
        self._on_completion_hook = on_completion_hook
        self._on_missed_hook = on_missed_hook
        self._on_proposal_hook = on_proposal_hook

    def transition(
        self,
        *,
        commitment_id: int,
        to_state: str,
        actor: str,
        reason: str | None = None,
        context: Mapping[str, object] | None = None,
        confidence: float | None = None,
        provenance_id: UUID | None = None,
        now: datetime | None = None,
    ) -> CommitmentStateTransition | CommitmentTransitionProposal:
        """Update commitment state or return a proposal for user confirmation."""
        if actor not in {"user", "system"}:
            raise ValueError(f"Unsupported transition actor: {actor}")
        authority = evaluate_transition_authority(
            to_state=to_state,
            actor=actor,
            confidence=confidence,
        )
        if not authority.allow_transition and actor == "system":
            proposal = self._create_proposal(
                commitment_id=commitment_id,
                to_state=to_state,
                actor=actor,
                reason=reason,
                context=context,
                confidence=confidence,
                threshold=authority.threshold,
                provenance_id=provenance_id,
                now=now,
            )
            if self._on_proposal_hook is not None:
                self._on_proposal_hook(proposal)
            return proposal
        if not authority.allow_transition:
            raise ValueError(
                "Transition blocked: confidence below threshold or missing. "
                f"effective_confidence={authority.effective_confidence} "
                f"threshold={authority.threshold} "
                f"reason={authority.reason}"
            )
        run_completion_hook = to_state in {"COMPLETED", "CANCELED"}
        run_missed_hook = to_state == "MISSED"
        with closing(self._session_factory()) as session:
            session.expire_on_commit = False
            try:
                commitment = _fetch_commitment(session, commitment_id)
                from_state = commitment.state
                timestamp = to_utc(now or datetime.now(timezone.utc))
                if actor == "user":
                    cancel_pending_proposals(
                        session,
                        commitment_id=commitment_id,
                        decided_by=actor,
                        decided_at=timestamp,
                        reason="user_transition_override",
                    )

                _apply_updates(
                    commitment,
                    CommitmentUpdateInput(state=to_state),
                    allow_state_change=True,
                )
                commitment.updated_at = timestamp

                transition = create_transition_record(
                    session,
                    CommitmentStateTransitionCreateInput(
                        commitment_id=commitment_id,
                        from_state=from_state,
                        to_state=to_state,
                        actor=actor,
                        reason=reason,
                        context=context,
                        confidence=confidence,
                        provenance_id=provenance_id,
                        transitioned_at=timestamp,
                    ),
                    now=timestamp,
                )
                session.commit()
            except Exception:
                session.rollback()
                raise

        if run_completion_hook and self._on_completion_hook is not None:
            self._on_completion_hook(commitment_id)
        if run_missed_hook and self._on_missed_hook is not None:
            try:
                self._on_missed_hook(commitment)
            except Exception:
                logger.exception(
                    "Missed transition hook failed: commitment_id=%s",
                    commitment_id,
                )

        return transition

    def _create_proposal(
        self,
        *,
        commitment_id: int,
        to_state: str,
        actor: str,
        reason: str | None,
        context: Mapping[str, object] | None,
        confidence: float | None,
        threshold: float,
        provenance_id: UUID | None,
        now: datetime | None,
    ) -> CommitmentTransitionProposal:
        """Persist a transition proposal without changing commitment state."""
        with closing(self._session_factory()) as session:
            session.expire_on_commit = False
            try:
                commitment = _fetch_commitment(session, commitment_id)
                timestamp = to_utc(now or datetime.now(timezone.utc))
                cancel_pending_proposals(
                    session,
                    commitment_id=commitment_id,
                    decided_by=actor,
                    decided_at=timestamp,
                    reason="superseded_by_new_proposal",
                )
                proposal = create_transition_proposal_record(
                    session,
                    CommitmentTransitionProposalCreateInput(
                        commitment_id=commitment_id,
                        from_state=commitment.state,
                        to_state=to_state,
                        actor=actor,
                        confidence=confidence,
                        threshold=threshold,
                        reason=reason,
                        context=context,
                        provenance_id=provenance_id,
                        proposed_at=timestamp,
                    ),
                    now=timestamp,
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
        return proposal
