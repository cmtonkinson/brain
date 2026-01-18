"""Approval workflow helpers for proposal artifacts and token validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import uuid4

from .context import SkillContext
from .registry import OpRuntimeEntry, SkillRuntimeEntry
from .registry_schema import AutonomyLevel

PROPOSAL_VERSION = "1.0"
DEFAULT_TTL_SECONDS = 3600
APPROVAL_REASONS = {"approval_required", "review_required"}
APPROVAL_TOKEN_REASON_MAP = {
    "expired": "expired",
    "actor_mismatch": "invalid",
    "proposal_mismatch": "invalid",
    "unknown": "invalid",
}


@dataclass(frozen=True)
class ProposalContext:
    """Execution context captured for an approval proposal."""

    actor: str
    channel: str
    trace_id: str
    invocation_id: str


@dataclass(frozen=True)
class ApprovalProposal:
    """Approval proposal payload for attention routing and audit."""

    proposal_version: str
    proposal_id: str
    action_kind: str
    action_name: str
    action_version: str
    autonomy: str
    required_capabilities: list[str]
    policy_tags: list[str]
    reason_for_review: str
    context: ProposalContext
    redactions: dict[str, list[str]]
    created_at: str
    expires_at: str


@dataclass(frozen=True)
class ApprovalDecision:
    """Record of an approval decision for a proposal."""

    proposal_id: str
    actor: str
    decision: str
    decided_at: str
    reason: str | None = None
    token_used: bool = False


@dataclass(frozen=True)
class ApprovalToken:
    """Approval token record scoped to a proposal and actor."""

    token: str
    actor: str
    proposal_id: str
    expires_at: datetime


@dataclass(frozen=True)
class ApprovalTokenValidation:
    """Result of validating an approval token."""

    valid: bool
    reason: str | None = None


class ApprovalTokenValidator(Protocol):
    """Protocol for approval token validation backends."""

    def validate(self, token: str, actor: str, proposal_id: str) -> ApprovalTokenValidation:
        """Validate token scope and expiration for an approval request."""
        ...


class ApprovalRecorder(Protocol):
    """Protocol for recording approval proposals and decisions."""

    def record_proposal(self, proposal: ApprovalProposal) -> None:
        """Persist an approval proposal for later review."""
        ...

    def record_decision(self, decision: ApprovalDecision) -> None:
        """Persist an approval decision for later audit."""
        ...


class NullApprovalTokenValidator:
    """Default validator that rejects all approval tokens."""

    def validate(self, token: str, actor: str, proposal_id: str) -> ApprovalTokenValidation:
        """Return a failed validation result for any token."""
        return ApprovalTokenValidation(valid=False, reason="unknown")


class InMemoryApprovalTokenStore:
    """In-memory approval token store with TTL enforcement."""

    def __init__(self) -> None:
        """Initialize the in-memory token store."""
        self._tokens: dict[str, ApprovalToken] = {}

    def issue(self, actor: str, proposal_id: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
        """Issue an approval token for a proposal and actor."""
        token = uuid4().hex
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        self._tokens[token] = ApprovalToken(
            token=token,
            actor=actor,
            proposal_id=proposal_id,
            expires_at=expires_at,
        )
        return token

    def validate(self, token: str, actor: str, proposal_id: str) -> ApprovalTokenValidation:
        """Validate that a token matches the actor and proposal and is not expired."""
        record = self._tokens.get(token)
        if record is None:
            return ApprovalTokenValidation(valid=False, reason="unknown")
        if datetime.now(timezone.utc) >= record.expires_at:
            return ApprovalTokenValidation(valid=False, reason="expired")
        if record.actor != actor:
            return ApprovalTokenValidation(valid=False, reason="actor_mismatch")
        if record.proposal_id != proposal_id:
            return ApprovalTokenValidation(valid=False, reason="proposal_mismatch")
        return ApprovalTokenValidation(valid=True)


class NullApprovalRecorder:
    """Recorder that drops approval proposals and decisions."""

    def record_proposal(self, proposal: ApprovalProposal) -> None:
        """Discard proposal records."""
        return None

    def record_decision(self, decision: ApprovalDecision) -> None:
        """Discard decision records."""
        return None


class InMemoryApprovalRecorder:
    """In-memory recorder for proposals and approval decisions."""

    def __init__(self) -> None:
        """Initialize the recorder history."""
        self.proposals: list[ApprovalProposal] = []
        self.decisions: list[ApprovalDecision] = []

    def record_proposal(self, proposal: ApprovalProposal) -> None:
        """Store a proposal in memory."""
        self.proposals.append(proposal)

    def record_decision(self, decision: ApprovalDecision) -> None:
        """Store a decision in memory."""
        self.decisions.append(decision)


def approval_required(entry: SkillRuntimeEntry | OpRuntimeEntry) -> bool:
    """Return True when an entry requires explicit approval or review."""
    return entry.autonomy == AutonomyLevel.L1 or "requires_review" in entry.definition.policy_tags


def approval_denial_reason(reasons: list[str]) -> str | None:
    """Return the approval reason to use for proposal creation."""
    for reason in reasons:
        if reason in APPROVAL_REASONS:
            return reason
    return None


def approval_token_reason_label(reason: str | None) -> str:
    """Normalize token validation reasons for policy metadata and decisions."""
    if reason is None:
        return "valid"
    return APPROVAL_TOKEN_REASON_MAP.get(reason, "invalid")


def build_proposal_id(
    entry: SkillRuntimeEntry | OpRuntimeEntry,
    context: SkillContext,
    inputs: dict[str, Any],
) -> str:
    """Build a deterministic proposal identifier for an action instance."""
    payload = {
        "action": {
            "kind": "skill" if isinstance(entry, SkillRuntimeEntry) else "op",
            "name": entry.definition.name,
            "version": entry.definition.version,
            "autonomy": entry.autonomy.value,
        },
        "context": {
            "actor": context.actor or "",
            "channel": context.channel or "",
            "trace_id": context.trace_id,
            "invocation_id": context.invocation_id,
        },
        "inputs": _redact_inputs(inputs, entry.definition.redaction),
    }
    digest = hashlib.sha256(_stable_json_dumps(payload).encode("utf-8")).hexdigest()
    return digest


def build_proposal(
    entry: SkillRuntimeEntry | OpRuntimeEntry,
    context: SkillContext,
    inputs: dict[str, Any],
    reason: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> ApprovalProposal:
    """Build an approval proposal artifact for an action request."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)
    redactions = {
        "inputs": list(entry.definition.redaction.inputs) if entry.definition.redaction else [],
    }
    proposal_id = build_proposal_id(entry, context, inputs)
    return ApprovalProposal(
        proposal_version=PROPOSAL_VERSION,
        proposal_id=proposal_id,
        action_kind="skill" if isinstance(entry, SkillRuntimeEntry) else "op",
        action_name=entry.definition.name,
        action_version=entry.definition.version,
        autonomy=entry.autonomy.value,
        required_capabilities=list(entry.definition.capabilities),
        policy_tags=list(entry.definition.policy_tags),
        reason_for_review=reason,
        context=ProposalContext(
            actor=context.actor or "",
            channel=context.channel or "",
            trace_id=context.trace_id,
            invocation_id=context.invocation_id,
        ),
        redactions=redactions,
        created_at=now.isoformat(),
        expires_at=expires_at.isoformat(),
    )


def _stable_json_dumps(payload: dict[str, Any]) -> str:
    """Serialize payloads to a stable JSON string."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _redact_inputs(inputs: dict[str, Any], redaction: Any) -> dict[str, Any]:
    """Return inputs with redacted fields masked for proposal hashing."""
    if not redaction or not getattr(redaction, "inputs", None):
        return inputs
    masked = dict(inputs)
    for redacted_field in redaction.inputs:
        if redacted_field in masked:
            masked[redacted_field] = "<redacted>"
    return masked
