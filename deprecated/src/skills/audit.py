"""Audit logging with redaction for skill executions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .context import SkillContext
from .registry import SkillRuntimeEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditEvent:
    """Structured audit record for a skill execution."""

    trace_id: str
    span_id: str
    skill: str
    version: str
    status: str
    duration_ms: int | None
    actor: str | None
    channel: str | None
    invocation_id: str
    parent_invocation_id: str | None
    capabilities: list[str]
    side_effects: list[str]
    inputs: dict[str, Any] | None = None
    outputs: dict[str, Any] | None = None
    error: str | None = None
    policy_reasons: list[str] | None = None
    policy_metadata: dict[str, str] | None = None


class AuditLogger:
    """Audit logger for skill execution events with redaction."""

    def record(
        self,
        skill: SkillRuntimeEntry,
        context: SkillContext,
        status: str,
        duration_ms: int | None,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
        policy_reasons: list[str] | None = None,
        policy_metadata: dict[str, str] | None = None,
    ) -> None:
        """Record a skill execution event after applying redactions."""
        redacted_inputs = _redact_payload(inputs, _redaction_fields(skill, "inputs"))
        redacted_outputs = _redact_payload(outputs, _redaction_fields(skill, "outputs"))

        event = AuditEvent(
            trace_id=context.trace_id,
            span_id=context.invocation_id,
            skill=skill.definition.name,
            version=skill.definition.version,
            status=status,
            duration_ms=duration_ms,
            actor=context.actor,
            channel=context.channel,
            invocation_id=context.invocation_id,
            parent_invocation_id=context.parent_invocation_id,
            capabilities=list(skill.definition.capabilities),
            side_effects=list(skill.definition.side_effects),
            inputs=redacted_inputs,
            outputs=redacted_outputs,
            error=error,
            policy_reasons=policy_reasons,
            policy_metadata=policy_metadata,
        )
        logger.info("skill_audit", extra=event.__dict__)


def _redaction_fields(skill: SkillRuntimeEntry, kind: str) -> set[str]:
    """Return the set of redacted fields for inputs or outputs."""
    if skill.definition.redaction is None:
        return set()
    return set(getattr(skill.definition.redaction, kind, []))


def _redact_payload(payload: dict[str, Any] | None, fields: set[str]) -> dict[str, Any] | None:
    """Redact configured fields from a payload."""
    if payload is None:
        return None
    if not fields:
        return payload
    redacted = dict(payload)
    for field in fields:
        if field in redacted:
            redacted[field] = "[REDACTED]"
    return redacted
