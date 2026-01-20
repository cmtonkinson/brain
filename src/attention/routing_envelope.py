"""Builders for normalized attention routing envelopes."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from typing import Any

from attention.envelope_schema import (
    ActionAuthorizationContext,
    NotificationEnvelope,
    ProvenanceInput,
    RoutingEnvelope,
    RoutingIntent,
    SignalPayload,
)
from config import settings
from scheduler.actor_context import ScheduledActorContext
from skills.approvals import ApprovalProposal
from skills.context import SkillContext
from skills.registry import OpRuntimeEntry, SkillRuntimeEntry

DEFAULT_ROUTING_VERSION = "1.0.0"
DEFAULT_SIGNAL_CONFIDENCE = 0.9


def build_skill_invocation_envelope(
    entry: SkillRuntimeEntry,
    context: SkillContext,
    inputs: dict[str, Any],
) -> RoutingEnvelope:
    """Build a routing envelope for a skill invocation."""
    return _build_entry_envelope(
        entry=entry,
        context=context,
        inputs=inputs,
        action_kind="skill",
        source_component="skill_runtime",
        routing_intent=RoutingIntent.LOG_ONLY,
    )


def build_op_invocation_envelope(
    entry: OpRuntimeEntry,
    context: SkillContext,
    inputs: dict[str, Any],
) -> RoutingEnvelope:
    """Build a routing envelope for an op invocation."""
    return _build_entry_envelope(
        entry=entry,
        context=context,
        inputs=inputs,
        action_kind="op",
        source_component="op_runtime",
        routing_intent=RoutingIntent.LOG_ONLY,
    )


def build_approval_envelope(
    proposal: ApprovalProposal,
    context: SkillContext,
) -> RoutingEnvelope:
    """Build a routing envelope for an approval request."""
    actor = (context.actor or "unknown").strip() or "unknown"
    channel = context.channel.strip() if context.channel else None
    signal_reference = f"approval:{proposal.proposal_id}"
    notification = NotificationEnvelope(
        version=DEFAULT_ROUTING_VERSION,
        source_component="policy_engine",
        origin_signal=signal_reference,
        confidence=1.0,
        provenance=[
            ProvenanceInput(
                input_type="approval_proposal",
                reference=proposal.proposal_id,
                description=f"{proposal.action_kind}:{proposal.action_name}",
            )
        ],
    )
    signal_payload = SignalPayload(
        from_number=settings.signal.phone_number or "unknown",
        to_number=actor,
        message=_format_approval_message(proposal),
    )
    return RoutingEnvelope(
        version=DEFAULT_ROUTING_VERSION,
        signal_type="approval.request",
        signal_reference=signal_reference,
        actor=actor,
        owner=actor,
        channel_hint=channel,
        urgency=0.7,
        channel_cost=0.2,
        content_type="approval",
        trace_id=context.trace_id,
        timestamp=datetime.now(timezone.utc),
        routing_intent=RoutingIntent.DELIVER,
        authorization=ActionAuthorizationContext(
            autonomy_level=proposal.autonomy,
            approval_status="requested",
            policy_tags=list(proposal.policy_tags),
        ),
        signal_payload=signal_payload,
        notification=notification,
    )


def build_signal_reply_envelope(
    *,
    from_number: str,
    to_number: str,
    message: str,
    source_component: str = "agent",
    trace_id: str | None = None,
) -> RoutingEnvelope:
    """Build a routing envelope for direct Signal replies."""
    reference = f"signal.reply:{uuid4().hex}"
    notification = NotificationEnvelope(
        version=DEFAULT_ROUTING_VERSION,
        source_component=source_component,
        origin_signal=reference,
        confidence=DEFAULT_SIGNAL_CONFIDENCE,
        provenance=[
            ProvenanceInput(
                input_type="signal_reply",
                reference=reference,
                description="Direct Signal reply.",
            )
        ],
    )
    return RoutingEnvelope(
        version=DEFAULT_ROUTING_VERSION,
        signal_type="signal.reply",
        signal_reference=reference,
        actor=source_component,
        owner=to_number,
        channel_hint="signal",
        urgency=0.9,
        channel_cost=0.1,
        content_type="message",
        trace_id=trace_id or uuid4().hex,
        timestamp=datetime.now(timezone.utc),
        signal_payload=SignalPayload(
            from_number=from_number,
            to_number=to_number,
            message=message,
        ),
        notification=notification,
    )


def build_schedule_failure_envelope(
    *,
    owner: str,
    schedule_id: int,
    execution_id: int,
    task_summary: str,
    failure_count: int,
    failure_threshold: int,
    throttle_window_seconds: int,
    last_error_code: str | None,
    last_error_message: str | None,
    source_component: str,
    urgency: float,
    channel_cost: float,
    trace_id: str | None,
    timestamp: datetime,
    actor_context: ScheduledActorContext,
) -> RoutingEnvelope:
    """Build a routing envelope for scheduled execution failures."""
    signal_reference = f"schedule.failure:{schedule_id}"
    notification = NotificationEnvelope(
        version=DEFAULT_ROUTING_VERSION,
        source_component=source_component,
        origin_signal=signal_reference,
        confidence=0.8,
        provenance=[
            ProvenanceInput(
                input_type="schedule",
                reference=str(schedule_id),
                description="Scheduled task failure threshold reached.",
            ),
            ProvenanceInput(
                input_type="execution",
                reference=str(execution_id),
                description=f"Failure count {failure_count}/{failure_threshold}.",
            ),
            ProvenanceInput(
                input_type="failure_threshold",
                reference=str(failure_threshold),
                description=f"throttle_window_seconds={throttle_window_seconds}",
            ),
        ],
    )
    signal_payload = SignalPayload(
        from_number=settings.signal.phone_number or "unknown",
        to_number=owner,
        message=_format_schedule_failure_message(
            task_summary=task_summary,
            schedule_id=schedule_id,
            execution_id=execution_id,
            failure_count=failure_count,
            failure_threshold=failure_threshold,
            last_error_code=last_error_code,
            last_error_message=last_error_message,
        ),
    )
    return RoutingEnvelope(
        version=DEFAULT_ROUTING_VERSION,
        signal_type="scheduled.failure",
        signal_reference=signal_reference,
        actor=actor_context.actor_type,
        owner=owner,
        channel_hint="signal",
        urgency=urgency,
        channel_cost=channel_cost,
        content_type="message",
        trace_id=trace_id or uuid4().hex,
        timestamp=timestamp,
        routing_intent=RoutingIntent.DELIVER,
        authorization=ActionAuthorizationContext(
            autonomy_level=actor_context.autonomy_level,
            approval_status="not_required",
            policy_tags=[],
        ),
        signal_payload=signal_payload,
        notification=notification,
    )


def _build_entry_envelope(
    entry: SkillRuntimeEntry | OpRuntimeEntry,
    context: SkillContext,
    inputs: dict[str, Any],
    *,
    action_kind: str,
    source_component: str,
    routing_intent: RoutingIntent,
) -> RoutingEnvelope:
    """Build a routing envelope for skill/op invocations."""
    actor = (context.actor or "unknown").strip() or "unknown"
    channel = context.channel.strip() if context.channel else None
    signal_reference = f"{action_kind}:{entry.definition.name}:{context.invocation_id}"
    input_count = len(inputs)
    notification = NotificationEnvelope(
        version=DEFAULT_ROUTING_VERSION,
        source_component=source_component,
        origin_signal=signal_reference,
        confidence=0.6,
        provenance=[
            ProvenanceInput(
                input_type="invocation",
                reference=context.invocation_id,
                description=f"{entry.definition.name} inputs={input_count}",
            )
        ],
    )
    return RoutingEnvelope(
        version=DEFAULT_ROUTING_VERSION,
        signal_type=f"{action_kind}.invocation",
        signal_reference=signal_reference,
        actor=actor,
        owner=actor,
        channel_hint=channel,
        urgency=0.1,
        channel_cost=0.9,
        content_type="internal",
        trace_id=context.trace_id,
        routing_intent=routing_intent,
        authorization=ActionAuthorizationContext(
            autonomy_level=entry.autonomy.value,
            approval_status="confirmed" if context.confirmed else "pending",
            policy_tags=list(entry.definition.policy_tags),
        ),
        notification=notification,
    )


def _format_approval_message(proposal: ApprovalProposal) -> str:
    """Format a human-readable approval request message."""
    lines = [
        f"Approval required: {proposal.action_kind} {proposal.action_name}",
        f"Version: {proposal.action_version}",
        f"Reason: {proposal.reason_for_review}",
        f"Proposal: {proposal.proposal_id}",
        f"Expires: {proposal.expires_at}",
    ]
    if proposal.required_capabilities:
        lines.append(f"Capabilities: {', '.join(sorted(proposal.required_capabilities))}")
    if proposal.policy_tags:
        lines.append(f"Policy tags: {', '.join(sorted(proposal.policy_tags))}")
    return "\n".join(lines)


def _format_schedule_failure_message(
    *,
    task_summary: str,
    schedule_id: int,
    execution_id: int,
    failure_count: int,
    failure_threshold: int,
    last_error_code: str | None,
    last_error_message: str | None,
) -> str:
    """Format a human-readable scheduled execution failure alert."""
    lines = [
        "Scheduled task failed repeatedly.",
        f"Task: {task_summary}",
        f"Schedule ID: {schedule_id}",
        f"Execution ID: {execution_id}",
        f"Failures: {failure_count} (threshold {failure_threshold})",
    ]
    if last_error_code or last_error_message:
        error_detail = last_error_code or "unknown_error"
        if last_error_message:
            error_detail = f"{error_detail}: {last_error_message}"
        lines.append(f"Last error: {error_detail}")
    return "\n".join(lines)
