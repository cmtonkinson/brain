"""Storage helpers for fail-closed routing recovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from attention.envelope_schema import NotificationEnvelope, ProvenanceInput, RoutingEnvelope
from models import (
    AttentionFailClosedPolicyTag,
    AttentionFailClosedProvenanceInput,
    AttentionFailClosedQueue,
)


def build_fail_closed_entry(
    envelope: RoutingEnvelope,
    reason: str,
    queued_at: datetime,
    retry_delay: timedelta,
) -> AttentionFailClosedQueue:
    """Create a fail-closed queue entry from a routing envelope."""
    signal_payload = envelope.signal_payload
    return AttentionFailClosedQueue(
        owner=envelope.owner,
        source_component=envelope.notification.source_component,
        actor=envelope.actor,
        channel=envelope.channel_hint or "signal",
        signal_reference=envelope.signal_reference,
        envelope_version=envelope.version,
        signal_type=envelope.signal_type,
        urgency=envelope.urgency,
        channel_cost=envelope.channel_cost,
        content_type=envelope.content_type,
        correlation_id=envelope.correlation_id,
        routing_intent=envelope.routing_intent.value,
        envelope_timestamp=envelope.timestamp,
        deadline=envelope.deadline,
        previous_severity=envelope.previous_severity,
        current_severity=envelope.current_severity,
        authorization_autonomy_level=(
            envelope.authorization.autonomy_level if envelope.authorization else None
        ),
        authorization_approval_status=(
            envelope.authorization.approval_status if envelope.authorization else None
        ),
        from_number=signal_payload.from_number if signal_payload else "unknown",
        to_number=signal_payload.to_number if signal_payload else "unknown",
        message=signal_payload.message if signal_payload else "missing_payload",
        notification_version=envelope.notification.version,
        notification_origin_signal=envelope.notification.origin_signal,
        notification_confidence=envelope.notification.confidence,
        reason=reason,
        queued_at=queued_at,
        retry_at=queued_at + retry_delay,
    )


def build_provenance_records(
    queue_id: int, provenance: list[ProvenanceInput]
) -> list[AttentionFailClosedProvenanceInput]:
    """Build provenance rows for a fail-closed queue entry."""
    return [
        AttentionFailClosedProvenanceInput(
            queue_id=queue_id,
            input_type=item.input_type,
            reference=item.reference,
            description=item.description,
        )
        for item in provenance
    ]


def build_policy_tag_records(
    queue_id: int, policy_tags: list[str]
) -> list[AttentionFailClosedPolicyTag]:
    """Build policy tag rows for a fail-closed queue entry."""
    return [AttentionFailClosedPolicyTag(queue_id=queue_id, tag=tag) for tag in policy_tags]


def load_fail_closed_envelope(
    session: Session, entry: AttentionFailClosedQueue
) -> RoutingEnvelope | None:
    """Rehydrate a routing envelope from a fail-closed queue entry."""
    if not entry.signal_reference or not entry.signal_type or not entry.envelope_version:
        return None
    provenance = (
        session.query(AttentionFailClosedProvenanceInput).filter_by(queue_id=entry.id).all()
    )
    policy_tags = session.query(AttentionFailClosedPolicyTag).filter_by(queue_id=entry.id).all()
    notification = NotificationEnvelope(
        version=entry.notification_version or entry.envelope_version,
        source_component=entry.source_component,
        origin_signal=entry.notification_origin_signal or entry.signal_reference,
        confidence=entry.notification_confidence or 0.9,
        provenance=[
            ProvenanceInput(
                input_type=item.input_type,
                reference=item.reference,
                description=item.description,
            )
            for item in provenance
        ]
        or [
            ProvenanceInput(
                input_type="fail_closed_queue",
                reference=entry.signal_reference,
                description="Recovered from fail-closed queue.",
            )
        ],
    )
    authorization = None
    if entry.authorization_autonomy_level or entry.authorization_approval_status or policy_tags:
        authorization = {
            "autonomy_level": entry.authorization_autonomy_level,
            "approval_status": entry.authorization_approval_status,
            "policy_tags": [item.tag for item in policy_tags],
        }
    payload = None
    if entry.from_number and entry.to_number and entry.message:
        payload = {
            "from_number": entry.from_number,
            "to_number": entry.to_number,
            "message": entry.message,
        }
    data = {
        "version": entry.envelope_version,
        "signal_type": entry.signal_type,
        "signal_reference": entry.signal_reference,
        "actor": entry.actor or entry.source_component,
        "owner": entry.owner,
        "channel_hint": entry.channel,
        "urgency": entry.urgency or 0.0,
        "channel_cost": entry.channel_cost or 0.0,
        "content_type": entry.content_type or "message",
        "correlation_id": entry.correlation_id or entry.signal_reference,
        "timestamp": entry.envelope_timestamp or datetime.now(timezone.utc),
        "deadline": entry.deadline,
        "previous_severity": entry.previous_severity,
        "current_severity": entry.current_severity,
        "routing_intent": entry.routing_intent or "DELIVER",
        "authorization": authorization,
        "signal_payload": payload,
        "notification": notification.model_dump(),
    }
    return RoutingEnvelope.model_validate(data)
