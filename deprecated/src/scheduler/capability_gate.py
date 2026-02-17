"""Read-only capability enforcement for predicate evaluation.

This module implements capability gating for predicate evaluation flows,
ensuring that only read-only Skills/Ops can be invoked under a scheduled
actor context. Any attempt to invoke side-effecting capabilities is denied
and recorded for audit purposes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable

from scheduler.actor_context import (
    SCHEDULED_ACTOR_TYPE,
    SCHEDULED_AUTONOMY_LEVEL,
    SCHEDULED_CHANNEL,
    SCHEDULED_PRIVILEGE_LEVEL,
    ScheduledActorContext,
)

logger = logging.getLogger(__name__)

# Read-only capabilities that are explicitly allowed during predicate evaluation.
# These capabilities can only observe state and cannot produce side effects.
READ_ONLY_CAPABILITIES: frozenset[str] = frozenset(
    [
        "obsidian.read",
        "memory.propose",  # propose is allowed since it doesn't commit
        "vault.search",
        "messaging.read",
        "calendar.read",
        "reminders.read",
        "blob.read",
        "filesystem.read",
        "github.read",
        "web.fetch",
        "scheduler.read",
        "policy.read",
    ]
)

# Side-effecting capabilities that are explicitly denied during predicate evaluation.
# These capabilities can create, update, delete, or send data.
SIDE_EFFECTING_CAPABILITIES: frozenset[str] = frozenset(
    [
        "obsidian.write",
        "memory.promote",
        "messaging.send",
        "attention.notify",
        "calendar.write",
        "reminders.write",
        "blob.store",
        "ingest.normalize",
        "filesystem.write",
        "github.write",
        "scheduler.write",
        "policy.write",
        "telemetry.emit",
    ]
)


class CapabilityDecision(str, Enum):
    """Decision outcomes for capability authorization checks."""

    ALLOW = "allow"
    DENY = "deny"


class DenialReasonCode(str, Enum):
    """Machine-readable reason codes for capability denials."""

    NOT_READ_ONLY = "not_read_only"
    UNKNOWN_CAPABILITY = "unknown_capability"
    INVALID_ACTOR_CONTEXT = "invalid_actor_context"
    MISSING_ACTOR_CONTEXT = "missing_actor_context"


@dataclass(frozen=True)
class CapabilityAuthorizationContext:
    """Actor context for capability authorization during predicate evaluation."""

    actor_type: str
    actor_id: str | None
    channel: str
    privilege_level: str
    autonomy_level: str
    trace_id: str
    request_id: str | None = None


@dataclass(frozen=True)
class CapabilityCheckResult:
    """Result of a capability authorization check."""

    decision: CapabilityDecision
    capability_id: str
    reason_code: str | None = None
    reason_message: str | None = None


@dataclass(frozen=True)
class CapabilityDenialAuditRecord:
    """Audit record for a denied capability invocation attempt."""

    capability_id: str
    decision: CapabilityDecision
    reason_code: str
    reason_message: str
    actor_type: str
    actor_id: str | None
    channel: str
    privilege_level: str
    autonomy_level: str
    trace_id: str
    request_id: str | None
    denied_at: datetime
    evaluation_context: str | None = None


class CapabilityGateError(Exception):
    """Raised when a capability check fails."""

    def __init__(
        self,
        code: str,
        message: str,
        capability_id: str,
        details: dict[str, object] | None = None,
    ) -> None:
        """Initialize the error with a machine-readable code and details."""
        super().__init__(message)
        self.code = code
        self.capability_id = capability_id
        self.details = details or {}


class CapabilityGate:
    """Capability gate enforcing read-only access for predicate evaluation.

    The gate validates that:
    1. The actor context is a valid scheduled actor context.
    2. The requested capability is in the read-only allowlist.
    3. Any denied attempts are recorded for audit.

    Usage:
        gate = CapabilityGate(audit_recorder=my_audit_callback)
        result = gate.check_capability("obsidian.read", actor_context)
        if result.decision == CapabilityDecision.DENY:
            # handle denial
        gate.require_capability("obsidian.read", actor_context)  # raises on denial
    """

    def __init__(
        self,
        *,
        audit_recorder: Callable[[CapabilityDenialAuditRecord], None] | None = None,
        now_provider: Callable[[], datetime] | None = None,
        read_only_capabilities: frozenset[str] | None = None,
    ) -> None:
        """Initialize the capability gate.

        Args:
            audit_recorder: Optional callback to record denial audit records.
            now_provider: Optional callable returning current UTC datetime.
            read_only_capabilities: Optional override for the read-only allowlist.
        """
        self._audit_recorder = audit_recorder
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._read_only_capabilities = read_only_capabilities or READ_ONLY_CAPABILITIES

    def check_capability(
        self,
        capability_id: str,
        actor_context: CapabilityAuthorizationContext,
        *,
        evaluation_context: str | None = None,
    ) -> CapabilityCheckResult:
        """Check if a capability is allowed under the given actor context.

        This method validates the actor context and capability against the
        read-only allowlist. Denied attempts are recorded via the audit_recorder
        if configured.

        Args:
            capability_id: The capability identifier to check.
            actor_context: The actor context for the evaluation.
            evaluation_context: Optional context string for audit records.

        Returns:
            CapabilityCheckResult with the authorization decision.
        """
        # Validate actor context is a scheduled actor
        context_result = self._validate_actor_context(actor_context)
        if context_result is not None:
            self._record_denial(
                capability_id,
                context_result.reason_code or DenialReasonCode.INVALID_ACTOR_CONTEXT.value,
                context_result.reason_message or "Invalid actor context.",
                actor_context,
                evaluation_context,
            )
            return context_result

        # Check if capability is read-only
        if capability_id in self._read_only_capabilities:
            return CapabilityCheckResult(
                decision=CapabilityDecision.ALLOW,
                capability_id=capability_id,
            )

        # Check if capability is known but side-effecting
        if capability_id in SIDE_EFFECTING_CAPABILITIES:
            result = CapabilityCheckResult(
                decision=CapabilityDecision.DENY,
                capability_id=capability_id,
                reason_code=DenialReasonCode.NOT_READ_ONLY.value,
                reason_message=f"Capability '{capability_id}' is side-effecting and not allowed during predicate evaluation.",
            )
            self._record_denial(
                capability_id,
                result.reason_code or "",
                result.reason_message or "",
                actor_context,
                evaluation_context,
            )
            return result

        # Unknown capability - deny by default
        result = CapabilityCheckResult(
            decision=CapabilityDecision.DENY,
            capability_id=capability_id,
            reason_code=DenialReasonCode.UNKNOWN_CAPABILITY.value,
            reason_message=f"Capability '{capability_id}' is not in the read-only allowlist.",
        )
        self._record_denial(
            capability_id,
            result.reason_code or "",
            result.reason_message or "",
            actor_context,
            evaluation_context,
        )
        return result

    def require_capability(
        self,
        capability_id: str,
        actor_context: CapabilityAuthorizationContext,
        *,
        evaluation_context: str | None = None,
    ) -> None:
        """Require a capability to be allowed, raising on denial.

        This method is a convenience wrapper around check_capability that
        raises CapabilityGateError if the capability is denied.

        Args:
            capability_id: The capability identifier to check.
            actor_context: The actor context for the evaluation.
            evaluation_context: Optional context string for audit records.

        Raises:
            CapabilityGateError: If the capability is denied.
        """
        result = self.check_capability(
            capability_id,
            actor_context,
            evaluation_context=evaluation_context,
        )
        if result.decision == CapabilityDecision.DENY:
            raise CapabilityGateError(
                code=result.reason_code or "denied",
                message=result.reason_message or f"Capability '{capability_id}' denied.",
                capability_id=capability_id,
                details={
                    "actor_type": actor_context.actor_type,
                    "channel": actor_context.channel,
                    "trace_id": actor_context.trace_id,
                },
            )

    def is_read_only(self, capability_id: str) -> bool:
        """Check if a capability is in the read-only allowlist.

        Args:
            capability_id: The capability identifier to check.

        Returns:
            True if the capability is read-only, False otherwise.
        """
        return capability_id in self._read_only_capabilities

    def is_side_effecting(self, capability_id: str) -> bool:
        """Check if a capability is known to be side-effecting.

        Args:
            capability_id: The capability identifier to check.

        Returns:
            True if the capability is side-effecting, False otherwise.
        """
        return capability_id in SIDE_EFFECTING_CAPABILITIES

    def _validate_actor_context(
        self,
        actor_context: CapabilityAuthorizationContext,
    ) -> CapabilityCheckResult | None:
        """Validate the actor context for predicate evaluation.

        Args:
            actor_context: The actor context to validate.

        Returns:
            CapabilityCheckResult with denial if invalid, None if valid.
        """
        if actor_context.actor_type != SCHEDULED_ACTOR_TYPE:
            return CapabilityCheckResult(
                decision=CapabilityDecision.DENY,
                capability_id="",
                reason_code=DenialReasonCode.INVALID_ACTOR_CONTEXT.value,
                reason_message=f"Actor type must be '{SCHEDULED_ACTOR_TYPE}' for predicate evaluation, got '{actor_context.actor_type}'.",
            )

        if actor_context.channel != SCHEDULED_CHANNEL:
            return CapabilityCheckResult(
                decision=CapabilityDecision.DENY,
                capability_id="",
                reason_code=DenialReasonCode.INVALID_ACTOR_CONTEXT.value,
                reason_message=f"Channel must be '{SCHEDULED_CHANNEL}' for predicate evaluation, got '{actor_context.channel}'.",
            )

        if actor_context.privilege_level != SCHEDULED_PRIVILEGE_LEVEL:
            return CapabilityCheckResult(
                decision=CapabilityDecision.DENY,
                capability_id="",
                reason_code=DenialReasonCode.INVALID_ACTOR_CONTEXT.value,
                reason_message=f"Privilege level must be '{SCHEDULED_PRIVILEGE_LEVEL}' for predicate evaluation, got '{actor_context.privilege_level}'.",
            )

        if actor_context.autonomy_level != SCHEDULED_AUTONOMY_LEVEL:
            return CapabilityCheckResult(
                decision=CapabilityDecision.DENY,
                capability_id="",
                reason_code=DenialReasonCode.INVALID_ACTOR_CONTEXT.value,
                reason_message=f"Autonomy level must be '{SCHEDULED_AUTONOMY_LEVEL}' for predicate evaluation, got '{actor_context.autonomy_level}'.",
            )

        return None

    def _record_denial(
        self,
        capability_id: str,
        reason_code: str,
        reason_message: str,
        actor_context: CapabilityAuthorizationContext,
        evaluation_context: str | None,
    ) -> None:
        """Record a capability denial for audit.

        Args:
            capability_id: The denied capability identifier.
            reason_code: Machine-readable denial reason.
            reason_message: Human-readable denial message.
            actor_context: The actor context of the denial.
            evaluation_context: Optional evaluation context string.
        """
        if self._audit_recorder is None:
            logger.warning(
                "Capability denied without audit recorder: capability=%s, reason=%s, trace_id=%s",
                capability_id,
                reason_code,
                actor_context.trace_id,
            )
            return

        record = CapabilityDenialAuditRecord(
            capability_id=capability_id,
            decision=CapabilityDecision.DENY,
            reason_code=reason_code,
            reason_message=reason_message,
            actor_type=actor_context.actor_type,
            actor_id=actor_context.actor_id,
            channel=actor_context.channel,
            privilege_level=actor_context.privilege_level,
            autonomy_level=actor_context.autonomy_level,
            trace_id=actor_context.trace_id,
            request_id=actor_context.request_id,
            denied_at=self._now_provider(),
            evaluation_context=evaluation_context,
        )
        try:
            self._audit_recorder(record)
        except Exception:
            logger.exception(
                "Failed to record capability denial audit: capability=%s, trace_id=%s",
                capability_id,
                actor_context.trace_id,
            )


def create_predicate_evaluation_actor_context(
    scheduled_context: ScheduledActorContext,
    trace_id: str,
    *,
    actor_id: str | None = None,
    request_id: str | None = None,
) -> CapabilityAuthorizationContext:
    """Create a capability authorization context from a scheduled actor context.

    This factory ensures the capability authorization context matches the
    scheduled actor context requirements for predicate evaluation.

    Args:
        scheduled_context: The scheduled actor context.
        trace_id: Trace ID for correlation.
        actor_id: Optional actor identifier.
        request_id: Optional request identifier.

    Returns:
        CapabilityAuthorizationContext for capability checks.
    """
    return CapabilityAuthorizationContext(
        actor_type=scheduled_context.actor_type,
        actor_id=actor_id,
        channel=scheduled_context.channel,
        privilege_level=scheduled_context.privilege_level,
        autonomy_level=scheduled_context.autonomy_level,
        trace_id=trace_id,
        request_id=request_id,
    )
