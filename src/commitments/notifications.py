"""Commitment notification routing helpers for the Attention Router."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable

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
from commitments.loop_closure_prompts import generate_loop_closure_prompt
from commitments.transition_proposal_prompts import generate_transition_proposal_prompt
from config import settings
from models import Commitment
from time_utils import to_local

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
    TRANSITION_PROPOSAL = "TRANSITION_PROPOSAL"
    DEDUPE_PROPOSAL = "DEDUPE_PROPOSAL"
    CREATION_APPROVAL_PROPOSAL = "CREATION_APPROVAL_PROPOSAL"


@dataclass(frozen=True)
class CommitmentNotification:
    """Payload describing a commitment notification to be routed."""

    commitment_id: int | None
    notification_type: CommitmentNotificationType
    message: str
    urgency: int | None = None
    channel: str = "signal"
    signal_reference: str | None = None
    provenance: list[ProvenanceInput] | None = None


def build_missed_commitment_message(commitment: Commitment) -> str:
    """Build a human-readable message for missed commitments."""
    description = commitment.description.strip()
    due_by = commitment.due_by
    if due_by is None:
        return f'Missed: "{description}" was not completed before its due time.'
    local_due = to_local(due_by)
    formatted = local_due.isoformat()
    return f'Missed: "{description}" was due by {formatted} and was not completed.'


def submit_missed_commitment_notification(
    router: AttentionRouter,
    commitment: Commitment,
    *,
    owner: str | None = None,
    now: datetime | None = None,
) -> RoutingResult:
    """Submit a MISSED commitment notification via the attention router."""
    message = build_missed_commitment_message(commitment)
    notification = CommitmentNotification(
        commitment_id=commitment.commitment_id,
        notification_type=CommitmentNotificationType.MISSED,
        message=message,
        urgency=commitment.urgency,
    )
    return submit_commitment_notification(
        router,
        notification,
        owner=owner,
        now=now,
    )


def submit_loop_closure_prompt_notification(
    router: AttentionRouter,
    commitment: Commitment,
    *,
    owner: str | None = None,
    now: datetime | None = None,
) -> RoutingResult | None:
    """Submit a loop-closure prompt notification when due_by is present."""
    prompt = generate_loop_closure_prompt(
        description=commitment.description,
        due_by=commitment.due_by,
    )
    if prompt is None:
        return None
    notification = CommitmentNotification(
        commitment_id=commitment.commitment_id,
        notification_type=CommitmentNotificationType.LOOP_CLOSURE,
        message=prompt,
        urgency=commitment.urgency,
    )
    return submit_commitment_notification(
        router,
        notification,
        owner=owner,
        now=now,
    )


def submit_transition_proposal_notification(
    router: AttentionRouter,
    commitment: Commitment,
    *,
    from_state: str,
    to_state: str,
    owner: str | None = None,
    now: datetime | None = None,
) -> RoutingResult:
    """Submit a transition proposal notification via the attention router."""
    prompt = generate_transition_proposal_prompt(
        description=commitment.description,
        from_state=from_state,
        to_state=to_state,
    )
    notification = CommitmentNotification(
        commitment_id=commitment.commitment_id,
        notification_type=CommitmentNotificationType.TRANSITION_PROPOSAL,
        message=prompt,
        urgency=commitment.urgency,
    )
    return submit_commitment_notification(
        router,
        notification,
        owner=owner,
        now=now,
    )


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
    provenance = _build_notification_provenance(notification, signal_reference=signal_reference)
    notification_envelope = NotificationEnvelope(
        version=DEFAULT_ROUTING_VERSION,
        source_component=source_component,
        origin_signal=signal_reference,
        confidence=DEFAULT_SIGNAL_CONFIDENCE,
        provenance=provenance,
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
    if notification.signal_reference is not None:
        return notification.signal_reference
    if notification.commitment_id is None:
        raise ValueError("notification.commitment_id is required when signal_reference is not set.")
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


def _build_notification_provenance(
    notification: CommitmentNotification,
    *,
    signal_reference: str,
) -> list[ProvenanceInput]:
    """Build required provenance rows for commitment notifications."""
    provenance: list[ProvenanceInput] = []
    if notification.commitment_id is not None:
        provenance.append(
            ProvenanceInput(
                input_type="commitment",
                reference=str(notification.commitment_id),
                description=f"Commitment {notification.notification_type.value} notification.",
            )
        )
    if notification.provenance:
        provenance.extend(notification.provenance)
    if not provenance:
        provenance.append(
            ProvenanceInput(
                input_type="notification",
                reference=signal_reference,
                description=f"{notification.notification_type.value} notification.",
            )
        )
    return provenance


def _clamp(value: float, *, minimum: float, maximum: float) -> float:
    """Clamp numeric values to a specified range."""
    return max(minimum, min(maximum, value))


def create_proposal_notification_hook(
    router: AttentionRouter,
    repository_factory: Callable[[], object],
) -> Callable[[object], None]:
    """Create a hook function that routes transition proposals via the attention router.

    Args:
        router: Attention router for routing notifications
        repository_factory: Factory that returns a CommitmentRepository instance

    Returns:
        Hook function that accepts CommitmentTransitionProposal objects
    """

    def hook(proposal: object) -> None:
        """Route a transition proposal notification."""
        try:
            # Get commitment details for notification
            repo = repository_factory()
            commitment = repo.get_by_id(proposal.commitment_id)
            if commitment is None:
                logger.warning(
                    "Cannot route proposal notification: commitment not found: commitment_id=%s",
                    proposal.commitment_id,
                )
                return

            # Submit proposal notification
            submit_transition_proposal_notification(
                router,
                commitment,
                from_state=str(proposal.from_state),
                to_state=str(proposal.to_state),
                owner=commitment.owner,
                now=proposal.proposed_at,
            )
            logger.info(
                "Routed transition proposal notification: proposal_id=%s commitment_id=%s %s→%s",
                proposal.proposal_id,
                proposal.commitment_id,
                proposal.from_state,
                proposal.to_state,
            )
        except Exception:
            logger.exception(
                "Failed to route transition proposal notification: proposal_id=%s commitment_id=%s",
                getattr(proposal, "proposal_id", None),
                getattr(proposal, "commitment_id", None),
            )

    return hook
