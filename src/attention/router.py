"""Attention router entry point for outbound notifications."""

from __future__ import annotations

import logging
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable
from uuid import uuid4

from sqlalchemy.orm import Session

from attention.assessment_engine import (
    BaseAssessmentOutcome,
    HIGH_URGENCY,
    LOW_URGENCY,
    assess_base_signal,
)
from attention.audit import AttentionAuditLogger
from attention.channel_selection import ChannelSelectionInputs, select_channel
from attention.decision_records import DecisionRecordInput, persist_decision_record
from attention.envelope_rendering import render_envelope_metadata
from attention.envelope_schema import (
    EnvelopeDecision,
    NotificationEnvelope,
    ProvenanceInput,
    RoutingEnvelope,
    RoutingIntent,
    SignalPayload,
)
from attention.escalation import (
    EscalationInput,
    EscalationLevel,
    evaluate_escalation,
    record_escalation_decision,
)
from attention.policy_defaults import default_attention_policies
from attention.policy_engine import AuthorizationContext, PolicyInputs, apply_policies
from attention.policy_schema import AttentionPolicy
from attention.preference_application import (
    PreferenceApplicationInputs,
    apply_preferences,
    resolve_preference_flags,
)
from attention.rate_limiter import RateLimitConfig, RateLimitInput, evaluate_rate_limit
from attention.router_gate import activate_router_context, deactivate_router_context
from attention.storage import (
    get_notification_history_count_for_signal,
    record_notification_history,
)
from models import AttentionEscalationThreshold, AttentionFailClosedQueue
from models import NotificationEnvelope as NotificationEnvelopeRecord
from models import NotificationProvenanceInput
from services.database import get_sync_session
from services.signal import SignalClient

logger = logging.getLogger(__name__)

DEFAULT_FAIL_CLOSED_RETRY = timedelta(minutes=15)
IGNORED_ESCALATION_THRESHOLD = 2


@dataclass(frozen=True)
class OutboundSignal:
    """Outbound signal payload for legacy routing."""

    source_component: str
    channel: str
    from_number: str
    to_number: str
    message: str


@dataclass(frozen=True)
class RoutingResult:
    """Result of routing an outbound signal."""

    decision: str
    channel: str | None
    envelope_id: int | None = None
    decision_record_id: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class RouterConfig:
    """Configuration for attention routing decisions."""

    policies: list[AttentionPolicy] = field(default_factory=default_attention_policies)
    rate_limits: list[RateLimitConfig] = field(default_factory=list)
    default_channel: str = "signal"
    record_to_obsidian: bool = True


class AttentionRouter:
    """Attention router gate for outbound communication."""

    def __init__(
        self,
        signal_client: SignalClient | None = None,
        session_factory: Callable[[], Session] | None = None,
        config: RouterConfig | None = None,
    ) -> None:
        """Initialize the router with service clients and config."""
        self._signal_client = signal_client or SignalClient()
        self._session_factory = session_factory or get_sync_session
        self._config = config or RouterConfig()
        self._routed: list[RoutingEnvelope] = []

    async def route_envelope(self, envelope: RoutingEnvelope) -> RoutingResult:
        """Route a normalized attention envelope through policy and delivery."""
        self._routed.append(envelope)
        if envelope.routing_intent == RoutingIntent.LOG_ONLY:
            return _record_log_only(self, envelope)

        with closing(self._session_factory()) as session:
            audit_logger = AttentionAuditLogger(session)
            try:
                envelope_id = _persist_notification_envelope(session, envelope.notification)
                base_assessment = assess_base_signal(
                    session,
                    {
                        "signal_reference": envelope.signal_reference,
                        "owner": envelope.owner,
                        "source_component": envelope.notification.source_component,
                        "urgency": envelope.urgency,
                        "confidence": envelope.notification.confidence,
                        "channel_cost": envelope.channel_cost,
                        "channel": envelope.channel_hint or self._config.default_channel,
                        "timestamp": envelope.timestamp,
                        "topic": envelope.topic,
                        "category": envelope.category,
                    },
                    audit_logger=audit_logger,
                )
                preference_result = apply_preferences(
                    session,
                    PreferenceApplicationInputs(
                        owner=envelope.owner,
                        signal_reference=envelope.signal_reference,
                        signal_type=envelope.signal_type,
                        source_component=envelope.notification.source_component,
                        urgency_score=envelope.urgency,
                        channel=envelope.channel_hint or self._config.default_channel,
                        timestamp=envelope.timestamp,
                    ),
                    base_assessment.outcome,
                    audit_logger=audit_logger,
                )
                preference_flags = resolve_preference_flags(
                    session, envelope.owner, envelope.timestamp
                )
                policy_inputs = PolicyInputs(
                    signal_reference=envelope.signal_reference,
                    signal_type=envelope.signal_type,
                    source_component=envelope.notification.source_component,
                    urgency_level=_urgency_level(envelope.urgency),
                    urgency_score=envelope.urgency,
                    confidence=envelope.notification.confidence,
                    channel_cost=envelope.channel_cost,
                    preferences=preference_flags,
                    timestamp=envelope.timestamp,
                    authorization=_build_authorization_context(envelope),
                )
                policy_decision = apply_policies(
                    self._config.policies,
                    policy_inputs,
                    base_assessment.outcome,
                    audit_logger=audit_logger,
                )
                decision = preference_result.final_decision
                if policy_decision.policy_outcome is not None:
                    decision = policy_decision.final_decision
                elif policy_decision.policy_explanation == "invalid_policy_outcome":
                    decision = policy_decision.final_decision
                decision = _apply_ignored_escalation(
                    session,
                    envelope,
                    decision,
                    default_channel=self._config.default_channel,
                )
                channel_result = select_channel(
                    ChannelSelectionInputs(
                        decision=decision,
                        signal_type=envelope.signal_type,
                        urgency_score=envelope.urgency,
                        channel_cost=envelope.channel_cost,
                        content_type=envelope.content_type,
                        record_to_obsidian=self._config.record_to_obsidian,
                    )
                )
                final_decision = channel_result.final_decision
                primary_channel = channel_result.primary_channel
                rate_limit = _apply_rate_limit(
                    session,
                    audit_logger,
                    envelope,
                    primary_channel,
                    base_assessment.outcome,
                    self._config.rate_limits,
                )
                if rate_limit is not None:
                    final_decision = rate_limit
                    primary_channel = None

                delivered = await _deliver_primary_channel(
                    self._signal_client,
                    envelope,
                    primary_channel,
                    envelope_id,
                    audit_logger,
                    base_assessment.outcome.value,
                    policy_decision.policy_outcome,
                    final_decision,
                    session,
                )
                if not delivered and primary_channel:
                    final_decision = "LOG_ONLY"
                    primary_channel = None

                audit_logger.log_signal(
                    source_component=envelope.notification.source_component,
                    signal_reference=envelope.signal_reference,
                    base_assessment=base_assessment.outcome.value,
                    policy_outcome=policy_decision.policy_outcome,
                    final_decision=final_decision,
                )

                if policy_decision.policy_outcome is None:
                    audit_logger.log_routing(
                        source_component=envelope.notification.source_component,
                        signal_reference=envelope.signal_reference,
                        base_assessment=base_assessment.outcome.value,
                        policy_outcome=None,
                        final_decision=final_decision,
                    )

                decision_record = persist_decision_record(
                    session,
                    DecisionRecordInput(
                        signal_reference=envelope.signal_reference,
                        channel=primary_channel,
                        base_assessment=base_assessment.outcome.value,
                        policy_outcome=policy_decision.policy_outcome,
                        final_decision=final_decision,
                        explanation=policy_decision.policy_explanation or "router_decision",
                    ),
                    audit_logger=audit_logger,
                )
                record_notification_history(
                    session,
                    owner=envelope.owner,
                    signal_reference=envelope.signal_reference,
                    outcome=final_decision,
                    channel=primary_channel,
                    decided_at=envelope.timestamp,
                )

                session.commit()
                return RoutingResult(
                    decision=final_decision,
                    channel=primary_channel,
                    envelope_id=envelope_id,
                    decision_record_id=decision_record.record_id,
                )
            except Exception as exc:
                session.rollback()
                try:
                    audit_logger.log_fail_closed(
                        source_component=envelope.notification.source_component,
                        signal_reference=envelope.signal_reference,
                        base_assessment="LOG_ONLY",
                        reason="routing_exception",
                    )
                    _queue_fail_closed_signal(session, envelope, reason="routing_exception")
                    session.commit()
                except Exception:
                    session.rollback()
                    logger.exception(
                        "Fail-closed queueing failed for signal=%s.",
                        envelope.signal_reference,
                    )
                logger.exception("Routing failed for signal=%s.", envelope.signal_reference)
                return RoutingResult(
                    decision="LOG_ONLY",
                    channel=None,
                    envelope_id=None,
                    decision_record_id=None,
                    error=str(exc),
                )

    async def route_signal(self, signal: OutboundSignal) -> RoutingResult:
        """Route a legacy outbound signal through the attention router."""
        envelope = _build_legacy_envelope(signal)
        return await self.route_envelope(envelope)

    def routed_signals(self) -> list[RoutingEnvelope]:
        """Return routed envelopes for testing and inspection."""
        return list(self._routed)

    def routed_sources(self) -> list[str]:
        """Return routed source component labels for inspection."""
        return [envelope.notification.source_component for envelope in self._routed]

    def policies_available(self) -> bool:
        """Return True when routing policies are available."""
        return bool(self._config.policies)


def _record_log_only(router: AttentionRouter, envelope: RoutingEnvelope) -> RoutingResult:
    """Persist a log-only decision for routing requests."""
    with closing(router._session_factory()) as session:
        audit_logger = AttentionAuditLogger(session)
        envelope_id = _persist_notification_envelope(session, envelope.notification)
        audit_logger.log_signal(
            source_component=envelope.notification.source_component,
            signal_reference=envelope.signal_reference,
            base_assessment=BaseAssessmentOutcome.SUPPRESS.value,
            policy_outcome="log_only",
            final_decision="LOG_ONLY",
        )
        record = persist_decision_record(
            session,
            DecisionRecordInput(
                signal_reference=envelope.signal_reference,
                channel=None,
                base_assessment=BaseAssessmentOutcome.SUPPRESS.value,
                policy_outcome="log_only",
                final_decision="LOG_ONLY",
                explanation="routing_intent_log_only",
            ),
            audit_logger=audit_logger,
        )
        record_notification_history(
            session,
            owner=envelope.owner,
            signal_reference=envelope.signal_reference,
            outcome="LOG_ONLY",
            channel=None,
            decided_at=envelope.timestamp,
        )
        session.commit()
        return RoutingResult(
            decision="LOG_ONLY",
            channel=None,
            envelope_id=envelope_id,
            decision_record_id=record.record_id,
        )


def _queue_fail_closed_signal(
    session: Session,
    envelope: RoutingEnvelope,
    *,
    reason: str,
    now: datetime | None = None,
) -> None:
    """Queue a Signal payload for retry when routing fails."""
    payload = envelope.signal_payload
    if payload is None:
        logger.warning(
            "Fail-closed queue skipped; missing signal payload for %s.",
            envelope.signal_reference,
        )
        return
    queued_at = now or datetime.now(timezone.utc)
    session.add(
        AttentionFailClosedQueue(
            owner=envelope.owner,
            source_component=envelope.notification.source_component,
            from_number=payload.from_number,
            to_number=payload.to_number,
            channel=envelope.channel_hint or "signal",
            message=payload.message,
            reason=reason,
            queued_at=queued_at,
            retry_at=queued_at + DEFAULT_FAIL_CLOSED_RETRY,
        )
    )


def _persist_notification_envelope(session: Session, envelope: NotificationEnvelope) -> int | None:
    """Persist a notification envelope and provenance inputs."""
    try:
        record = NotificationEnvelopeRecord(
            version=envelope.version,
            source_component=envelope.source_component,
            origin_signal=envelope.origin_signal,
            confidence=envelope.confidence,
        )
        session.add(record)
        session.flush()
        for entry in envelope.provenance:
            session.add(
                NotificationProvenanceInput(
                    envelope_id=record.id,
                    input_type=entry.input_type,
                    reference=entry.reference,
                    description=entry.description,
                )
            )
        session.flush()
        return record.id
    except Exception:
        logger.exception("Failed to persist notification envelope.")
        return None


def _apply_rate_limit(
    session: Session,
    audit_logger: AttentionAuditLogger,
    envelope: RoutingEnvelope,
    channel: str | None,
    base_assessment: BaseAssessmentOutcome,
    configs: Iterable[RateLimitConfig],
) -> str | None:
    """Evaluate rate limits and return a decision override if blocked."""
    if channel is None:
        return None
    config = next((item for item in configs if item.channel == channel), None)
    if config is None:
        return None
    decision = evaluate_rate_limit(
        session,
        RateLimitInput(
            owner=envelope.owner,
            signal_reference=envelope.signal_reference,
            source_component=envelope.notification.source_component,
            channel=channel,
            channel_cost=envelope.channel_cost,
            timestamp=envelope.timestamp,
            base_assessment=base_assessment.value,
        ),
        config,
        audit_logger=audit_logger,
    )
    if decision.allowed:
        return None
    return decision.decision


async def _deliver_primary_channel(
    signal_client: SignalClient,
    envelope: RoutingEnvelope,
    channel: str | None,
    envelope_id: int | None,
    audit_logger: AttentionAuditLogger,
    base_assessment: str,
    policy_outcome: str | None,
    final_decision: str,
    session: Session,
) -> bool:
    """Deliver the routed signal via the primary channel."""
    if channel is None:
        return False
    if channel != "signal":
        logger.warning("Unsupported channel %s; defaulting to LOG_ONLY.", channel)
        return False
    if envelope.signal_payload is None:
        logger.error("Signal payload missing for signal delivery.")
        return False

    message = envelope.signal_payload.message
    if envelope_id is not None:
        metadata = render_envelope_metadata(session, envelope_id, channel)
        if metadata.decision == EnvelopeDecision.ACCEPT.value and metadata.metadata:
            message = f"{message}\n\n{metadata.metadata}"

    token = activate_router_context()
    try:
        ok = await signal_client.send_message(
            envelope.signal_payload.from_number,
            envelope.signal_payload.to_number,
            message,
            source_component=envelope.notification.source_component,
        )
        if ok and envelope_id is not None:
            audit_logger.log_notification(
                source_component=envelope.notification.source_component,
                signal_reference=envelope.signal_reference,
                base_assessment=base_assessment,
                policy_outcome=policy_outcome,
                final_decision=final_decision,
                envelope_id=envelope_id,
            )
        return ok
    finally:
        deactivate_router_context(token)


def _urgency_level(score: float) -> str:
    """Return a string urgency level for policy matching."""
    if score >= HIGH_URGENCY:
        return "high"
    if score <= LOW_URGENCY:
        return "low"
    return "medium"


def _build_authorization_context(envelope: RoutingEnvelope) -> AuthorizationContext | None:
    """Normalize authorization context for policy evaluation."""
    if envelope.authorization is None:
        return None
    return AuthorizationContext(
        autonomy_level=envelope.authorization.autonomy_level,
        approval_status=envelope.authorization.approval_status,
        policy_tags=set(envelope.authorization.policy_tags),
    )


def _build_legacy_envelope(signal: OutboundSignal) -> RoutingEnvelope:
    """Build a routing envelope from a legacy outbound signal."""
    reference = f"legacy:{uuid4().hex}"
    notification = NotificationEnvelope(
        version="1.0.0",
        source_component=signal.source_component,
        origin_signal=reference,
        confidence=0.9,
        provenance=[
            ProvenanceInput(
                input_type="legacy_signal",
                reference=reference,
                description="Legacy outbound signal.",
            )
        ],
    )
    return RoutingEnvelope(
        version="1.0.0",
        signal_type="legacy.signal",
        signal_reference=reference,
        actor=signal.from_number,
        owner=signal.to_number,
        channel_hint=signal.channel,
        urgency=0.9,
        channel_cost=0.1,
        content_type="message",
        correlation_id=uuid4().hex,
        routing_intent=RoutingIntent.DELIVER,
        signal_payload=SignalPayload(
            from_number=signal.from_number,
            to_number=signal.to_number,
            message=signal.message,
        ),
        notification=notification,
    )


def _apply_ignored_escalation(
    session: Session,
    envelope: RoutingEnvelope,
    decision: str,
    *,
    default_channel: str,
) -> str:
    """Escalate signals that have been ignored repeatedly."""
    decision_type = decision.split(":", 1)[0]
    if decision_type in {"NOTIFY", "ESCALATE"}:
        return decision

    ignored_count = get_notification_history_count_for_signal(
        session,
        owner=envelope.owner,
        signal_reference=envelope.signal_reference,
        outcomes={"LOG_ONLY", "SUPPRESS", "DROP"},
    )
    if ignored_count < IGNORED_ESCALATION_THRESHOLD:
        return decision

    threshold_record = (
        session.query(AttentionEscalationThreshold)
        .filter_by(owner=envelope.owner, signal_type=envelope.signal_type)
        .order_by(AttentionEscalationThreshold.created_at.desc())
        .first()
    )
    ignore_threshold = (
        threshold_record.threshold if threshold_record else IGNORED_ESCALATION_THRESHOLD
    )
    inputs = EscalationInput(
        owner=envelope.owner,
        signal_reference=envelope.signal_reference,
        current_level=EscalationLevel.NONE,
        ignored_count=ignored_count,
        ignore_threshold=ignore_threshold,
        timestamp=envelope.timestamp,
    )
    escalation = evaluate_escalation(inputs)
    if not escalation.escalated:
        return decision

    record_escalation_decision(session, inputs, escalation)
    return f"ESCALATE:{default_channel}"
