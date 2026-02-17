"""Rate limiting for attention notifications."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from attention.audit import AttentionAuditLogger
from attention.assessment_engine import HIGH_CHANNEL_COST
from models import NotificationHistoryEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitConfig:
    """Rate limit configuration for a channel."""

    channel: str
    max_per_window: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitInput:
    """Inputs required for rate limiting decisions."""

    owner: str
    signal_reference: str
    source_component: str
    channel: str
    channel_cost: float
    timestamp: datetime
    base_assessment: str


@dataclass(frozen=True)
class RateLimitDecision:
    """Result of rate limiting evaluation."""

    allowed: bool
    decision: str
    reason: str


def evaluate_rate_limit(
    session: Session,
    inputs: RateLimitInput,
    config: RateLimitConfig,
    audit_logger: AttentionAuditLogger | None = None,
) -> RateLimitDecision:
    """Evaluate rate limits for the given channel and time window."""
    if config.max_per_window <= 0 or config.window_seconds <= 0:
        logger.error("Invalid rate limit configuration for channel=%s.", config.channel)
        decision = RateLimitDecision(
            allowed=False,
            decision="LOG_ONLY",
            reason="invalid_rate_limit_config",
        )
        _audit_rate_limit(audit_logger, inputs, decision)
        return decision

    window_start = inputs.timestamp - timedelta(seconds=config.window_seconds)
    count = (
        session.query(NotificationHistoryEntry)
        .filter(NotificationHistoryEntry.owner == inputs.owner)
        .filter(NotificationHistoryEntry.channel == config.channel)
        .filter(NotificationHistoryEntry.created_at >= window_start)
        .filter(
            or_(
                NotificationHistoryEntry.outcome.like("NOTIFY%"),
                NotificationHistoryEntry.outcome.like("ESCALATE%"),
            )
        )
        .count()
    )
    if count < config.max_per_window:
        decision = RateLimitDecision(
            allowed=True,
            decision="ALLOW",
            reason="within_limit",
        )
        _audit_rate_limit(audit_logger, inputs, decision)
        return decision

    decision_type = "DEFER" if inputs.channel_cost >= HIGH_CHANNEL_COST else "BATCH"
    decision = RateLimitDecision(
        allowed=False,
        decision=decision_type,
        reason="rate_limit_exceeded",
    )
    _audit_rate_limit(audit_logger, inputs, decision)
    return decision


def _audit_rate_limit(
    audit_logger: AttentionAuditLogger | None,
    inputs: RateLimitInput,
    decision: RateLimitDecision,
) -> None:
    """Record rate limit decisions in the audit log."""
    if not audit_logger:
        return
    audit_logger.log_rate_limit(
        source_component=inputs.source_component,
        signal_reference=inputs.signal_reference,
        base_assessment=inputs.base_assessment,
        final_decision=decision.decision,
        reason=decision.reason,
    )
