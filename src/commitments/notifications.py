"""Commitment notification routing helpers for the Attention Router."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from attention.envelope_schema import (
    ActionAuthorizationContext,
    NotificationEnvelope,
    ProvenanceInput,
    RoutingEnvelope,
    RoutingIntent,
    SignalPayload,
)
from attention.router import AttentionRouter, RoutingResult
from attention.routing_envelope import DEFAULT_ROUTING_VERSION, DEFAULT_SIGNAL_CONFIDENCE
from config import settings

logger = logging.getLogger(__name__)

DEFAULT_PRIORITY = 0.5
DEFAULT_CHANNEL_COST = 0.2
DEFAULT_SOURCE_COMPONENT = "commitments"


class CommitmentNotificationType(str, Enum):
    """Supported commitment notification types."""

    MISSED = "MISSED"
    REMINDER = "REMINDER"
    REVIEW = "REVIEW"
    BATCH = "BATCH"
    LOOP_CLOSURE = "LOOP_CLOSURE"


@dataclass(frozen=True)
class CommitmentNotification:
    """Payload describing a commitment notification to be routed."""

    commitment_id: int
    notification_type: CommitmentNotificationType
    message: str
    urgency: int | None = None
    channel: str = "signal"


def normalize_urgency_priority(urgency: int | None) -> float:
    """Normalize urgency 1-100 into the 0.01-1.00 priority range."""
    if urgency is None:
        return DEFAULT_PRIORITY
    return _clamp(float(urgency) / 100.0, minimum=0.01, maximum=1.0)


def submit_commitment_notification(
    router: AttentionRouter,
    notification: CommitmentNotification,
    *,
    owner: str | None = None,
    source_component: str = DEFAULT_SOURCE_COMPONENT,
    channel_cost: float = DEFAULT_CHANNEL_COST,
    now: datetime | None = None,
) -> RoutingResult:
    """Build and route a commitment notification through the attention router."""
    resolved_owner = owner or _resolve_default_owner()
    if resolved_owner is None:
        logger.error(
            "Commitment notification skipped: no owner configured. commitment_id=%s",
            notification.commitment_id,
        )
        return RoutingResult(
            decision="LOG_ONLY",
            channel=None,
            envelope_id=None,
            decision_record_id=None,
            error="missing_owner",
        )

    timestamp = now or datetime.now(timezone.utc)
    priority = normalize_urgency_priority(notification.urgency)
    envelope = _build_routing_envelope(
        notification=notification,
        owner=resolved_owner,
        source_component=source_component,
        urgency=priority,
        channel_cost=channel_cost,
        timestamp=timestamp,
    )

    try:
        result = asyncio.run(router.route_envelope(envelope))
    except RuntimeError as exc:
        logger.exception(
            "Commitment notification routing failed: commitment_id=%s notification_type=%s error=%s",
            notification.commitment_id,
            notification.notification_type.value,
            exc,
        )
        return RoutingResult(
            decision="LOG_ONLY",
            channel=None,
            envelope_id=None,
            decision_record_id=None,
            error=str(exc),
        )
    except Exception as exc:
        logger.exception(
            "Commitment notification routing failed unexpectedly: commitment_id=%s notification_type=%s",
            notification.commitment_id,
            notification.notification_type.value,
        )
        return RoutingResult(
            decision="LOG_ONLY",
            channel=None,
            envelope_id=None,
            decision_record_id=None,
            error=str(exc),
        )

    _log_routing_result(notification, result)
    return result


def _build_routing_envelope(
    *,
    notification: CommitmentNotification,
    owner: str,
    source_component: str,
    urgency: float,
    channel_cost: float,
    timestamp: datetime,
) -> RoutingEnvelope:
    """Create a RoutingEnvelope for a commitment notification."""
    signal_reference = _signal_reference(notification)
    notification_envelope = NotificationEnvelope(
        version=DEFAULT_ROUTING_VERSION,
        source_component=source_component,
        origin_signal=signal_reference,
        confidence=DEFAULT_SIGNAL_CONFIDENCE,
        provenance=[
            ProvenanceInput(
                input_type="commitment",
                reference=str(notification.commitment_id),
                description=f"Commitment {notification.notification_type.value} notification.",
            )
        ],
    )
    signal_payload = SignalPayload(
        from_number=settings.signal.phone_number or "unknown",
        to_number=owner,
        message=notification.message,
    )
    return RoutingEnvelope(
        version=DEFAULT_ROUTING_VERSION,
        signal_type=_signal_type(notification.notification_type),
        signal_reference=signal_reference,
        actor=source_component,
        owner=owner,
        channel_hint=notification.channel,
        urgency=urgency,
        channel_cost=channel_cost,
        content_type="message",
        timestamp=timestamp,
        routing_intent=RoutingIntent.DELIVER,
        authorization=ActionAuthorizationContext(
            autonomy_level="system",
            approval_status="not_required",
            policy_tags=[],
        ),
        signal_payload=signal_payload,
        notification=notification_envelope,
    )


def _signal_reference(notification: CommitmentNotification) -> str:
    """Build a stable reference string for the notification."""
    return f"commitment.{notification.notification_type.value.lower()}:{notification.commitment_id}"


def _signal_type(notification_type: CommitmentNotificationType) -> str:
    """Return the routing signal_type for a commitment notification."""
    return f"commitment.{notification_type.value.lower()}"


def _resolve_default_owner() -> str | None:
    """Return the default notification owner from Signal allowlists."""
    allowlist = settings.signal.allowed_senders_by_channel.get("signal")
    if allowlist:
        return allowlist[0]
    if settings.signal.allowed_senders:
        return settings.signal.allowed_senders[0]
    return None


def _log_routing_result(notification: CommitmentNotification, result: RoutingResult) -> None:
    """Log commitment notification routing outcomes."""
    if result.error:
        logger.warning(
            "Commitment notification rejected: commitment_id=%s notification_type=%s decision=%s error=%s",
            notification.commitment_id,
            notification.notification_type.value,
            result.decision,
            result.error,
        )
        return

    logger.info(
        "Commitment notification routed: commitment_id=%s notification_type=%s decision=%s channel=%s",
        notification.commitment_id,
        notification.notification_type.value,
        result.decision,
        result.channel,
    )


def _clamp(value: float, *, minimum: float, maximum: float) -> float:
    """Clamp numeric values to a specified range."""
    return max(minimum, min(maximum, value))
