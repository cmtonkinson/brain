"""Review and escalation for suppressed signals."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from attention.escalation import EscalationDecision, EscalationInput, EscalationLevel
from attention.escalation import record_escalation_decision
from models import (
    AttentionBatch,
    AttentionBatchItem,
    AttentionReviewLog,
    NotificationHistoryEntry,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SuppressedReviewItem:
    """Suppressed signal review item."""

    signal_reference: str
    outcome: str
    channel: str | None


@dataclass(frozen=True)
class SuppressedReviewResult:
    """Result of building a suppressed signals review."""

    batch_id: int | None
    items: list[SuppressedReviewItem]


@dataclass(frozen=True)
class ReviewActionResult:
    """Result of applying a review action."""

    action: str
    escalation: EscalationDecision | None


def create_suppressed_review_batch(
    session: Session,
    owner: str,
    since: datetime,
    now: datetime,
) -> SuppressedReviewResult:
    """Collect suppressed signals for review and create a batch."""
    suppressed = (
        session.query(NotificationHistoryEntry)
        .filter(NotificationHistoryEntry.owner == owner)
        .filter(NotificationHistoryEntry.created_at >= since)
        .filter(NotificationHistoryEntry.outcome.in_(["SUPPRESS", "LOG_ONLY", "DROP"]))
        .order_by(NotificationHistoryEntry.created_at.desc())
        .all()
    )
    if not suppressed:
        _log_review_action(session, owner, None, "noop")
        return SuppressedReviewResult(batch_id=None, items=[])

    batch = AttentionBatch(
        owner=owner,
        batch_type="suppressed_review",
        scheduled_for=now,
    )
    session.add(batch)
    session.flush()

    items: list[SuppressedReviewItem] = []
    for idx, entry in enumerate(suppressed, start=1):
        session.add(
            AttentionBatchItem(
                batch_id=batch.id,
                signal_reference=entry.signal_reference,
                rank=idx,
            )
        )
        items.append(
            SuppressedReviewItem(
                signal_reference=entry.signal_reference,
                outcome=entry.outcome,
                channel=entry.channel,
            )
        )
    session.flush()
    return SuppressedReviewResult(batch_id=batch.id, items=items)


def apply_review_action(
    session: Session,
    owner: str,
    signal_reference: str,
    action: str,
    current_level: EscalationLevel,
    timestamp: datetime,
) -> ReviewActionResult:
    """Apply a review action and optionally trigger escalation."""
    _log_review_action(session, owner, signal_reference, action)
    if action == "escalate":
        inputs = EscalationInput(
            owner=owner,
            signal_reference=signal_reference,
            current_level=current_level,
            ignored_count=None,
            timestamp=timestamp,
        )
        decision = EscalationDecision(
            escalated=True,
            level=EscalationLevel(min(current_level + 1, EscalationLevel.HIGH)),
            trigger="review_escalation",
        )
        record_escalation_decision(session, inputs, decision)
        return ReviewActionResult(action=action, escalation=decision)
    return ReviewActionResult(action=action, escalation=None)


def _log_review_action(
    session: Session,
    owner: str,
    signal_reference: str | None,
    action: str,
) -> None:
    """Persist a review log entry."""
    session.add(
        AttentionReviewLog(
            owner=owner,
            signal_reference=signal_reference,
            action=action,
        )
    )
    session.flush()
