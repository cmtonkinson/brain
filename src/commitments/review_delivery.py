"""Review delivery and engagement tracking helpers."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable, Iterable

from sqlalchemy.orm import Session

from attention.router import AttentionRouter, RoutingResult
from commitments.notifications import (
    CommitmentNotification,
    CommitmentNotificationType,
    submit_commitment_notification,
)
from commitments.repository import CommitmentRepository, CommitmentUpdateInput
from commitments.review_summary import ReviewSummaryResult
from time_utils import to_utc

logger = logging.getLogger(__name__)


def deliver_review_summary(
    router: AttentionRouter,
    *,
    review_id: int,
    summary: ReviewSummaryResult,
    owner: str | None = None,
    now: datetime | None = None,
) -> RoutingResult:
    """Deliver a review summary via the attention router."""
    timestamp = to_utc(now or datetime.now(timezone.utc))
    message = _build_review_message(summary)
    notification = CommitmentNotification(
        commitment_id=review_id,
        notification_type=CommitmentNotificationType.REVIEW,
        message=message,
        urgency=None,
        channel="signal",
    )
    logger.info(
        "Weekly review delivery submitted: review_id=%s timestamp=%s",
        review_id,
        timestamp.isoformat(),
    )
    result = submit_commitment_notification(
        router,
        notification,
        owner=owner,
        now=timestamp,
    )
    logger.info(
        "Weekly review delivery result: review_id=%s decision=%s timestamp=%s",
        review_id,
        result.decision,
        timestamp.isoformat(),
    )
    return result


def record_review_engagement(
    review_id: int,
    commitment_ids: Iterable[int],
    *,
    session_factory: Callable[[], Session],
    engaged_at: datetime | None = None,
) -> None:
    """Record engagement with a review by updating reviewed_at timestamps."""
    timestamp = to_utc(engaged_at or datetime.now(timezone.utc))
    repo = CommitmentRepository(session_factory)
    updated_ids = []
    for commitment_id in commitment_ids:
        repo.update(
            commitment_id,
            CommitmentUpdateInput(reviewed_at=timestamp),
            now=timestamp,
        )
        updated_ids.append(commitment_id)
    logger.info(
        "Weekly review engagement recorded: review_id=%s commitment_ids=%s timestamp=%s",
        review_id,
        updated_ids,
        timestamp.isoformat(),
    )


def _build_review_message(summary: ReviewSummaryResult) -> str:
    """Format the review summary into a message payload."""
    structured_payload = json.dumps(asdict(summary.structured))
    return f"{summary.narrative}\n\nStructured summary (JSON):\n{structured_payload}"


__all__ = [
    "deliver_review_summary",
    "record_review_engagement",
]
