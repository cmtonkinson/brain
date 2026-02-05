"""Review delivery and engagement tracking helpers."""

from __future__ import annotations

import json
import logging
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

from sqlalchemy.orm import Session

from attention.router import AttentionRouter, RoutingResult
from commitments.notifications import (
    CommitmentNotification,
    CommitmentNotificationType,
    submit_commitment_notification,
)
from commitments.review_summary import ReviewSummaryResult
from models import Commitment, CommitmentReviewItem, CommitmentReviewRun
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


def mark_review_delivered(
    review_id: int,
    *,
    session_factory: Callable[[], Session],
    delivered_at: datetime,
) -> None:
    """Mark a review run as delivered at the provided timestamp."""
    timestamp = to_utc(delivered_at)
    with closing(session_factory()) as session:
        session.expire_on_commit = False
        run = session.get(CommitmentReviewRun, review_id)
        if run is None:
            raise ValueError(f"Review run not found: {review_id}")
        run.delivered_at = timestamp
        session.commit()


def record_review_engagement(
    review_id: int,
    *,
    session_factory: Callable[[], Session],
    engaged_at: datetime | None = None,
) -> None:
    """Record engagement with a review by updating reviewed_at timestamps."""
    timestamp = to_utc(engaged_at or datetime.now(timezone.utc))
    updated_ids = _record_review_engagement(
        review_id,
        session_factory=session_factory,
        engaged_at=timestamp,
    )
    logger.info(
        "Weekly review engagement recorded: review_id=%s commitment_ids=%s timestamp=%s",
        review_id,
        updated_ids,
        timestamp.isoformat(),
    )


def record_review_items(
    review_id: int,
    commitment_ids: Iterable[int],
    *,
    session_factory: Callable[[], Session],
    created_at: datetime | None = None,
) -> None:
    """Persist review item mappings for a review run."""
    ids = sorted({int(commitment_id) for commitment_id in commitment_ids})
    if not ids:
        return
    timestamp = to_utc(created_at or datetime.now(timezone.utc))
    with closing(session_factory()) as session:
        session.expire_on_commit = False
        try:
            for commitment_id in ids:
                session.add(
                    CommitmentReviewItem(
                        review_run_id=review_id,
                        commitment_id=commitment_id,
                        created_at=timestamp,
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise


def maybe_record_review_engagement(
    owner: str,
    *,
    session_factory: Callable[[], Session],
    engaged_at: datetime,
    window_minutes: int,
) -> bool:
    """Record review engagement if a recent review was delivered."""
    timestamp = to_utc(engaged_at)
    window_start = timestamp - timedelta(minutes=window_minutes)
    with closing(session_factory()) as session:
        session.expire_on_commit = False
        run = (
            session.query(CommitmentReviewRun)
            .filter(
                CommitmentReviewRun.owner == owner,
                CommitmentReviewRun.delivered_at.is_not(None),
                CommitmentReviewRun.engaged_at.is_(None),
                CommitmentReviewRun.delivered_at >= window_start,
                CommitmentReviewRun.delivered_at <= timestamp,
            )
            .order_by(CommitmentReviewRun.delivered_at.desc())
            .first()
        )
        if run is None:
            return False
        _record_review_engagement_in_session(session, run, timestamp)
        session.commit()
        logger.info(
            "Weekly review engagement auto-recorded: review_id=%s owner=%s timestamp=%s",
            run.id,
            owner,
            timestamp.isoformat(),
        )
        return True


def _record_review_engagement(
    review_id: int,
    *,
    session_factory: Callable[[], Session],
    engaged_at: datetime,
) -> list[int]:
    """Record engagement within a managed session and return updated IDs."""
    with closing(session_factory()) as session:
        session.expire_on_commit = False
        run = session.get(CommitmentReviewRun, review_id)
        if run is None:
            raise ValueError(f"Review run not found: {review_id}")
        updated_ids = _record_review_engagement_in_session(session, run, engaged_at)
        session.commit()
        return updated_ids


def _record_review_engagement_in_session(
    session: Session,
    run: CommitmentReviewRun,
    engaged_at: datetime,
) -> list[int]:
    """Update review run + commitments with engagement using the same session."""
    if run.engaged_at is not None:
        return []
    run.engaged_at = engaged_at
    commitment_ids = [
        item.commitment_id
        for item in session.query(CommitmentReviewItem)
        .filter(CommitmentReviewItem.review_run_id == run.id)
        .all()
    ]
    if not commitment_ids:
        return []
    commitments = (
        session.query(Commitment).filter(Commitment.commitment_id.in_(commitment_ids)).all()
    )
    for commitment in commitments:
        commitment.reviewed_at = engaged_at
        commitment.updated_at = engaged_at
    return commitment_ids


def _build_review_message(summary: ReviewSummaryResult) -> str:
    """Format the review summary into a message payload."""
    structured_payload = json.dumps(asdict(summary.structured))
    return f"{summary.narrative}\n\nStructured summary (JSON):\n{structured_payload}"


__all__ = [
    "deliver_review_summary",
    "mark_review_delivered",
    "maybe_record_review_engagement",
    "record_review_engagement",
    "record_review_items",
]
