"""Attention assessment engine for base routing decisions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from attention.audit import AttentionAuditLogger
from attention.holding import record_batched_signal, record_deferred_signal
from attention.storage import (
    get_attention_context_for_timestamp,
    get_notification_history_counts,
)

logger = logging.getLogger(__name__)

HIGH_URGENCY = 0.8
LOW_URGENCY = 0.3
HIGH_CONFIDENCE = 0.8
LOW_CONFIDENCE = 0.4
HIGH_CHANNEL_COST = 0.7
DEFAULT_HISTORY_WINDOW = timedelta(minutes=30)
DEFAULT_REEVALUATE_AFTER = timedelta(minutes=30)


class BaseAssessmentOutcome(str, Enum):
    """Allowed base assessment outcomes."""

    SUPPRESS = "SUPPRESS"
    DEFER = "DEFER"
    BATCH = "BATCH"
    NOTIFY = "NOTIFY"


@dataclass(frozen=True)
class BaseAssessment:
    """Result of a base assessment evaluation."""

    outcome: BaseAssessmentOutcome
    explanation: str


class AssessmentInput(BaseModel):
    """Normalized input payload for base assessment."""

    model_config = ConfigDict(extra="forbid")

    signal_reference: str = Field(..., min_length=1)
    owner: str = Field(..., min_length=1)
    source_component: str = Field(..., min_length=1)
    urgency: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    channel_cost: float = Field(..., ge=0.0, le=1.0)
    channel: str = Field(..., min_length=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    topic: str | None = None
    category: str | None = None

    @field_validator("signal_reference", "owner", "source_component", "channel")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        """Normalize required string fields."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Required fields must be non-empty strings.")
        return normalized

    @field_validator("topic", "category")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        """Normalize optional string fields."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Optional fields must be non-empty when provided.")
        return normalized


def assess_base_signal(
    session: Session,
    payload: dict[str, Any],
    audit_logger: AttentionAuditLogger | None = None,
    history_window: timedelta = DEFAULT_HISTORY_WINDOW,
    reevaluate_after: timedelta = DEFAULT_REEVALUATE_AFTER,
) -> BaseAssessment:
    """Assess a signal using urgency, confidence, context, and history."""
    try:
        inputs = AssessmentInput.model_validate(payload)
    except ValidationError as exc:
        logger.error("Assessment input validation failed: %s", exc)
        return BaseAssessment(
            outcome=BaseAssessmentOutcome.SUPPRESS,
            explanation="validation_failed",
        )

    context = get_attention_context_for_timestamp(session, inputs.owner, inputs.timestamp)
    history = get_notification_history_counts(
        session,
        owner=inputs.owner,
        start_at=inputs.timestamp - history_window,
        end_at=inputs.timestamp,
        channels=[inputs.channel],
        outcomes=[BaseAssessmentOutcome.NOTIFY.value],
    )
    recent_notifications = any(entry.count > 0 for entry in history)

    outcome = _determine_outcome(inputs, context.interruptible, recent_notifications)
    explanation = _build_explanation(inputs, context.interruptible, recent_notifications, outcome)

    if audit_logger:
        audit_logger.log_base_assessment(
            source_component=inputs.source_component,
            signal_reference=inputs.signal_reference,
            base_assessment=outcome.value,
        )

    if outcome == BaseAssessmentOutcome.DEFER:
        record_deferred_signal(
            session,
            owner=inputs.owner,
            signal_reference=inputs.signal_reference,
            source_component=inputs.source_component,
            reason=explanation,
            reevaluate_at=inputs.timestamp + reevaluate_after,
        )
    elif outcome == BaseAssessmentOutcome.BATCH:
        record_batched_signal(
            session,
            owner=inputs.owner,
            signal_reference=inputs.signal_reference,
            source_component=inputs.source_component,
            topic=inputs.topic or "general",
            category=inputs.category or "unspecified",
        )

    return BaseAssessment(outcome=outcome, explanation=explanation)


def _determine_outcome(
    inputs: AssessmentInput,
    interruptible: bool,
    recent_notifications: bool,
) -> BaseAssessmentOutcome:
    """Select a base outcome from assessment inputs."""
    if inputs.urgency >= HIGH_URGENCY and inputs.confidence >= HIGH_CONFIDENCE:
        return BaseAssessmentOutcome.NOTIFY

    if not interruptible:
        if inputs.urgency <= LOW_URGENCY or inputs.channel_cost >= HIGH_CHANNEL_COST:
            return (
                BaseAssessmentOutcome.BATCH
                if inputs.topic or inputs.category
                else BaseAssessmentOutcome.DEFER
            )
        return BaseAssessmentOutcome.DEFER

    if inputs.confidence <= LOW_CONFIDENCE:
        return BaseAssessmentOutcome.DEFER

    if recent_notifications and inputs.urgency <= HIGH_URGENCY:
        return BaseAssessmentOutcome.BATCH

    if inputs.channel_cost >= HIGH_CHANNEL_COST and inputs.urgency <= LOW_URGENCY:
        return BaseAssessmentOutcome.BATCH

    if inputs.urgency <= LOW_URGENCY:
        return (
            BaseAssessmentOutcome.BATCH
            if inputs.topic or inputs.category
            else BaseAssessmentOutcome.DEFER
        )

    return BaseAssessmentOutcome.NOTIFY


def _build_explanation(
    inputs: AssessmentInput,
    interruptible: bool,
    recent_notifications: bool,
    outcome: BaseAssessmentOutcome,
) -> str:
    """Construct an explanation string for audit logging."""
    parts = [
        f"outcome={outcome.value}",
        f"urgency={inputs.urgency:.2f}",
        f"confidence={inputs.confidence:.2f}",
        f"interruptible={str(interruptible).lower()}",
        f"recent_notifications={str(recent_notifications).lower()}",
        f"channel_cost={inputs.channel_cost:.2f}",
    ]
    return " ".join(parts)
