"""Miss detection callback handler for due-by schedules."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal

from sqlalchemy.orm import Session

from commitments.notifications import (
    submit_loop_closure_prompt_notification,
    submit_missed_commitment_notification,
)
from commitments.repository import CommitmentRepository, CommitmentUpdateInput
from commitments.schedule_links import CommitmentScheduleLinkRepository
from commitments.transition_service import CommitmentStateTransitionService
from time_utils import to_utc
from attention.router import AttentionRouter
from models import Commitment

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MissDetectionCallbackResult:
    """Outcome of processing a miss detection callback."""

    status: Literal["missed", "noop", "no_link"]
    schedule_id: int
    commitment_id: int | None
    commitment_state: str | None = None


def handle_miss_detection_callback(
    session_factory: Callable[[], Session],
    *,
    schedule_id: int,
    trace_id: str | None = None,
    now: datetime | None = None,
    router: AttentionRouter | None = None,
) -> MissDetectionCallbackResult:
    """Handle a miss detection callback by transitioning OPEN commitments to MISSED."""
    link_repo = CommitmentScheduleLinkRepository(session_factory)
    commitment = link_repo.resolve_commitment_by_schedule_id(schedule_id)
    if commitment is None:
        logger.info(
            "Miss detection callback ignored: no active link for schedule_id=%s",
            schedule_id,
        )
        return MissDetectionCallbackResult(
            status="no_link",
            schedule_id=schedule_id,
            commitment_id=None,
            commitment_state=None,
        )

    current_state = str(commitment.state)
    if current_state != "OPEN":
        return MissDetectionCallbackResult(
            status="noop",
            schedule_id=schedule_id,
            commitment_id=commitment.commitment_id,
            commitment_state=current_state,
        )

    timestamp = to_utc(now or datetime.now(timezone.utc))
    resolved_router = router or AttentionRouter()
    transition_service = CommitmentStateTransitionService(
        session_factory,
        on_missed_hook=lambda record: _dispatch_missed_notifications(
            resolved_router,
            record,
            timestamp=timestamp,
        ),
    )
    transition_service.transition(
        commitment_id=commitment.commitment_id,
        to_state="MISSED",
        actor="system",
        reason="due_by_expired",
        context=_build_transition_context(schedule_id=schedule_id, trace_id=trace_id),
        now=timestamp,
    )
    if commitment.ever_missed_at is None:
        CommitmentRepository(session_factory).update(
            commitment.commitment_id,
            CommitmentUpdateInput(ever_missed_at=timestamp),
            now=timestamp,
        )
    return MissDetectionCallbackResult(
        status="missed",
        schedule_id=schedule_id,
        commitment_id=commitment.commitment_id,
        commitment_state="MISSED",
    )


def _build_transition_context(
    *,
    schedule_id: int,
    trace_id: str | None,
) -> dict[str, object]:
    """Build audit context for miss detection transitions."""
    context: dict[str, object] = {"schedule_id": schedule_id}
    if trace_id:
        context["trace_id"] = trace_id
    return context


def _dispatch_missed_notifications(
    router: AttentionRouter,
    commitment: Commitment,
    *,
    timestamp: datetime,
) -> None:
    """Submit missed notifications and loop-closure prompts without raising."""
    try:
        submit_missed_commitment_notification(router, commitment, now=timestamp)
    except Exception:
        logger.exception(
            "Missed notification submission failed: commitment_id=%s",
            commitment.commitment_id,
        )
    try:
        submit_loop_closure_prompt_notification(router, commitment, now=timestamp)
    except Exception:
        logger.exception(
            "Loop-closure prompt delivery failed: commitment_id=%s",
            commitment.commitment_id,
        )


__all__ = [
    "MissDetectionCallbackResult",
    "handle_miss_detection_callback",
]
