"""Escalation evaluation for attention routing decisions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum

from sqlalchemy.orm import Session

from models import AttentionEscalationLog

logger = logging.getLogger(__name__)

DEFAULT_IGNORE_THRESHOLD = 3
DEFAULT_DEADLINE_WINDOW = timedelta(hours=1)


class EscalationLevel(IntEnum):
    """Ordered escalation levels."""

    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass(frozen=True)
class EscalationInput:
    """Inputs required to evaluate escalation."""

    owner: str
    signal_type: str | None
    signal_reference: str
    current_level: EscalationLevel | None
    ignored_count: int | None = None
    ignore_threshold: int = DEFAULT_IGNORE_THRESHOLD
    deadline: datetime | None = None
    deadline_window: timedelta = DEFAULT_DEADLINE_WINDOW
    previous_severity: int | None = None
    current_severity: int | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class EscalationDecision:
    """Escalation decision output."""

    escalated: bool
    level: EscalationLevel
    trigger: str | None


def evaluate_escalation(inputs: EscalationInput) -> EscalationDecision:
    """Evaluate escalation conditions and return the next escalation level."""
    if inputs.current_level is None:
        logger.warning("Missing escalation level for signal=%s.", inputs.signal_reference)
        return EscalationDecision(
            escalated=False,
            level=EscalationLevel.NONE,
            trigger=None,
        )

    trigger = _determine_trigger(inputs)
    if trigger is None:
        return EscalationDecision(
            escalated=False,
            level=inputs.current_level,
            trigger=None,
        )

    next_level = EscalationLevel(min(inputs.current_level + 1, EscalationLevel.HIGH))
    return EscalationDecision(
        escalated=True,
        level=next_level,
        trigger=trigger,
    )


def record_escalation_decision(
    session: Session,
    inputs: EscalationInput,
    decision: EscalationDecision,
) -> AttentionEscalationLog | None:
    """Persist an escalation decision log entry."""
    if not decision.escalated or not decision.trigger:
        return None
    entry = AttentionEscalationLog(
        owner=inputs.owner,
        signal_type=inputs.signal_type,
        signal_reference=inputs.signal_reference,
        trigger=decision.trigger,
        level=int(decision.level),
        timestamp=inputs.timestamp,
    )
    session.add(entry)
    session.flush()
    return entry


def _determine_trigger(inputs: EscalationInput) -> str | None:
    """Return the first escalation trigger that applies."""
    if inputs.ignored_count is not None and inputs.ignored_count >= inputs.ignore_threshold:
        return "ignored_repeatedly"
    if inputs.deadline and inputs.timestamp:
        if inputs.deadline - inputs.timestamp <= inputs.deadline_window:
            return "approaching_deadline"
    if (
        inputs.previous_severity is not None
        and inputs.current_severity is not None
        and inputs.current_severity > inputs.previous_severity
    ):
        return "increasing_severity"
    if inputs.ignored_count is None and inputs.deadline is None and inputs.current_severity is None:
        logger.warning("Missing escalation metadata for signal=%s.", inputs.signal_reference)
    return None


def get_latest_escalation_level(
    session: Session,
    owner: str,
    signal_type: str,
) -> EscalationLevel:
    """Return the latest escalation level for an owner and signal type."""
    record = (
        session.query(AttentionEscalationLog)
        .filter_by(owner=owner, signal_type=signal_type)
        .order_by(AttentionEscalationLog.timestamp.desc())
        .first()
    )
    if record is None:
        return EscalationLevel.NONE
    try:
        return EscalationLevel(record.level)
    except ValueError:
        logger.warning(
            "Invalid escalation level=%s for signal_type=%s; defaulting to NONE.",
            record.level,
            signal_type,
        )
        return EscalationLevel.NONE
