"""Execution helpers for loop-closure response intents."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Literal

from sqlalchemy.orm import Session

from commitments.loop_closure_parser import LoopClosureIntent
from commitments.miss_detection_scheduling import MissDetectionScheduleService
from commitments.progress_service import CommitmentProgressService
from commitments.repository import CommitmentRepository, CommitmentUpdateInput
from commitments.transition_service import CommitmentStateTransitionService
from commitments.transition_proposal_repository import (
    CommitmentTransitionProposalRepository,
)
from scheduler.adapter_interface import SchedulerAdapter
from time_utils import to_utc

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoopClosureActionRequest:
    """Request payload for executing a loop-closure intent."""

    commitment_id: int
    intent: LoopClosureIntent
    prompt: str
    response: str
    actor: str = "user"
    reason: str | None = None


@dataclass(frozen=True)
class LoopClosureActionResult:
    """Outcome of applying a loop-closure action."""

    status: Literal["completed", "canceled", "renegotiated", "reviewed", "noop"]
    commitment_id: int
    prior_state: str | None = None
    new_state: str | None = None
    new_due_by: datetime | None = None


class LoopClosureActionService:
    """Service to apply loop-closure response intents."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        schedule_adapter: SchedulerAdapter,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the loop-closure action service."""
        self._session_factory = session_factory
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._commitment_repo = CommitmentRepository(session_factory)
        self._proposal_repo = CommitmentTransitionProposalRepository(session_factory)
        self._transition_service = CommitmentStateTransitionService(session_factory)
        self._progress_service = CommitmentProgressService(session_factory)
        self._schedule_service = MissDetectionScheduleService(
            session_factory,
            schedule_adapter,
            now_provider=self._now_provider,
        )

    def apply_intent(self, request: LoopClosureActionRequest) -> LoopClosureActionResult:
        """Apply a loop-closure intent to the target commitment."""
        self._log_prompt_response(request)
        commitment = self._commitment_repo.get_by_id(request.commitment_id)
        if commitment is None:
            raise ValueError(f"Commitment not found: {request.commitment_id}")

        prior_state = str(commitment.state)
        if prior_state in {"COMPLETED", "CANCELED"}:
            return LoopClosureActionResult(
                status="noop",
                commitment_id=commitment.commitment_id,
                prior_state=prior_state,
                new_state=prior_state,
            )

        intent_type = request.intent.intent
        self._reconcile_pending_proposals(
            commitment_id=commitment.commitment_id,
            intent_type=intent_type,
            actor=request.actor,
        )
        if intent_type == "complete":
            timestamp = self._now_provider()
            self._transition_service.transition(
                commitment_id=commitment.commitment_id,
                to_state="COMPLETED",
                actor=request.actor,
                reason=request.reason or "loop_closure_complete",
                context=_build_action_context(request),
                now=timestamp,
            )
            self._schedule_service.remove_schedule(
                commitment_id=commitment.commitment_id,
                reason="commitment_resolved",
            )
            # Record progress for completion
            try:
                self._progress_service.record_progress(
                    commitment_id=commitment.commitment_id,
                    provenance_id=None,
                    occurred_at=timestamp,
                    summary="Commitment marked complete via loop closure",
                    snippet=request.response[:200] if request.response else None,
                    metadata={"actor": request.actor, "source": "loop_closure"},
                )
            except Exception:
                logger.exception(
                    "Failed to record progress for completion: commitment_id=%s",
                    commitment.commitment_id,
                )
            return LoopClosureActionResult(
                status="completed",
                commitment_id=commitment.commitment_id,
                prior_state=prior_state,
                new_state="COMPLETED",
            )
        if intent_type == "cancel":
            timestamp = self._now_provider()
            self._transition_service.transition(
                commitment_id=commitment.commitment_id,
                to_state="CANCELED",
                actor=request.actor,
                reason=request.reason or "loop_closure_cancel",
                context=_build_action_context(request),
                now=timestamp,
            )
            self._schedule_service.remove_schedule(
                commitment_id=commitment.commitment_id,
                reason="commitment_resolved",
            )
            # Record progress for cancellation
            try:
                self._progress_service.record_progress(
                    commitment_id=commitment.commitment_id,
                    provenance_id=None,
                    occurred_at=timestamp,
                    summary="Commitment canceled via loop closure",
                    snippet=request.response[:200] if request.response else None,
                    metadata={"actor": request.actor, "source": "loop_closure"},
                )
            except Exception:
                logger.exception(
                    "Failed to record progress for cancellation: commitment_id=%s",
                    commitment.commitment_id,
                )
            return LoopClosureActionResult(
                status="canceled",
                commitment_id=commitment.commitment_id,
                prior_state=prior_state,
                new_state="CANCELED",
            )

        if intent_type == "renegotiate":
            timestamp = self._now_provider()
            new_due_by = _normalize_due_by(request.intent.new_due_by)
            updated = self._commitment_repo.update(
                commitment.commitment_id,
                CommitmentUpdateInput(due_by=new_due_by),
                now=timestamp,
            )
            self._schedule_service.ensure_schedule(
                commitment_id=commitment.commitment_id,
                due_by=updated.due_by,
            )
            # Record progress for renegotiation
            try:
                summary = f"Commitment renegotiated, new due date: {new_due_by.strftime('%Y-%m-%d') if new_due_by else 'cleared'}"
                self._progress_service.record_progress(
                    commitment_id=commitment.commitment_id,
                    provenance_id=None,
                    occurred_at=timestamp,
                    summary=summary,
                    snippet=request.response[:200] if request.response else None,
                    metadata={
                        "actor": request.actor,
                        "source": "loop_closure",
                        "new_due_by": new_due_by.isoformat() if new_due_by else None,
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to record progress for renegotiation: commitment_id=%s",
                    commitment.commitment_id,
                )
            return LoopClosureActionResult(
                status="renegotiated",
                commitment_id=commitment.commitment_id,
                prior_state=prior_state,
                new_state=str(updated.state),
                new_due_by=updated.due_by,
            )

        if intent_type == "review":
            timestamp = self._now_provider()
            updated = self._commitment_repo.update(
                commitment.commitment_id,
                CommitmentUpdateInput(reviewed_at=timestamp),
                now=timestamp,
            )
            return LoopClosureActionResult(
                status="reviewed",
                commitment_id=commitment.commitment_id,
                prior_state=prior_state,
                new_state=str(updated.state),
            )

        raise ValueError(f"Unsupported loop-closure intent: {intent_type}")

    def _log_prompt_response(self, request: LoopClosureActionRequest) -> None:
        """Log prompt-response pairs for observability."""
        timestamp = to_utc(self._now_provider())
        logger.info(
            "Loop-closure response: commitment_id=%s intent=%s timestamp=%s prompt=%s response=%s",
            request.commitment_id,
            request.intent.intent,
            timestamp.isoformat(),
            request.prompt,
            request.response,
        )

    def _reconcile_pending_proposals(
        self,
        *,
        commitment_id: int,
        intent_type: str,
        actor: str,
    ) -> None:
        """Approve or cancel pending proposals based on the loop-closure intent."""
        pending = self._proposal_repo.get_pending_for_commitment(commitment_id)
        if pending is None:
            return
        desired_state = _intent_to_state(intent_type)
        decided_at = self._now_provider()
        if desired_state is not None and pending.to_state == desired_state:
            self._proposal_repo.mark_approved(
                pending.proposal_id,
                decided_by=actor,
                decided_at=decided_at,
                reason="loop_closure_confirmed",
            )
            return
        self._proposal_repo.cancel_pending_for_commitment(
            commitment_id,
            decided_by=actor,
            decided_at=decided_at,
            reason="user_override",
        )


def _normalize_due_by(value: date | datetime | None) -> date | datetime | None:
    """Normalize due_by inputs, preserving date-only values for repository handling."""
    return value


def _build_action_context(request: LoopClosureActionRequest) -> dict[str, object]:
    """Build audit context payload for loop-closure actions."""
    return {
        "prompt": request.prompt,
        "response": request.response,
        "intent": request.intent.intent,
    }


def _intent_to_state(intent_type: str) -> str | None:
    """Map loop-closure intents to target states when applicable."""
    if intent_type == "complete":
        return "COMPLETED"
    if intent_type == "cancel":
        return "CANCELED"
    return None


__all__ = [
    "LoopClosureActionRequest",
    "LoopClosureActionResult",
    "LoopClosureActionService",
]
