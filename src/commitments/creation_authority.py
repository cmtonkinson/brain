"""Authority evaluation for commitment creation proposals."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from config import settings


class CommitmentCreationSource(str, Enum):
    """Enumerate commitment creation sources that affect authority."""

    USER = "user"
    AGENT = "agent"


@dataclass(frozen=True)
class CreationApprovalProposal:
    """Proposal payload returned when operator approval is required."""

    source: CommitmentCreationSource
    confidence: float
    threshold: float
    reason: str


@dataclass(frozen=True)
class CreationAuthorityDecision:
    """Result of authority evaluation for a creation request."""

    status: Literal["approved", "requires_approval"]
    allow_create: bool
    source: CommitmentCreationSource
    confidence: float
    threshold: float
    proposal: CreationApprovalProposal | None = None


@dataclass(frozen=True)
class CreationApprovalOutcome:
    """Outcome of an operator approval or rejection decision."""

    status: Literal["approved", "rejected"]
    allow_create: bool
    proposal: CreationApprovalProposal


def normalize_creation_source(
    source: CommitmentCreationSource | str,
) -> CommitmentCreationSource:
    """Normalize source inputs to the CommitmentCreationSource enum."""
    if isinstance(source, CommitmentCreationSource):
        return source
    normalized = source.strip().lower()
    if normalized == "user":
        return CommitmentCreationSource.USER
    if normalized == "agent":
        return CommitmentCreationSource.AGENT
    raise ValueError(f"Unknown commitment creation source: {source}")


def resolve_autonomous_creation_threshold() -> float:
    """Return the configured autonomous creation confidence threshold."""
    return settings.commitments.autonomous_creation_confidence_threshold


def evaluate_creation_authority(
    source: CommitmentCreationSource | str,
    *,
    confidence: float | None = None,
    threshold: float | None = None,
) -> CreationAuthorityDecision:
    """Evaluate creation authority and return approval requirements."""
    resolved_source = normalize_creation_source(source)
    resolved_confidence = 0.0 if confidence is None else confidence
    resolved_threshold = resolve_autonomous_creation_threshold() if threshold is None else threshold

    if resolved_source is CommitmentCreationSource.USER:
        return CreationAuthorityDecision(
            status="approved",
            allow_create=True,
            source=resolved_source,
            confidence=resolved_confidence,
            threshold=resolved_threshold,
        )

    if resolved_confidence >= resolved_threshold:
        return CreationAuthorityDecision(
            status="approved",
            allow_create=True,
            source=resolved_source,
            confidence=resolved_confidence,
            threshold=resolved_threshold,
        )

    proposal = CreationApprovalProposal(
        source=resolved_source,
        confidence=resolved_confidence,
        threshold=resolved_threshold,
        reason="agent_suggested_below_threshold",
    )
    return CreationAuthorityDecision(
        status="requires_approval",
        allow_create=False,
        source=resolved_source,
        confidence=resolved_confidence,
        threshold=resolved_threshold,
        proposal=proposal,
    )


def approve_creation(proposal: CreationApprovalProposal) -> CreationApprovalOutcome:
    """Approve a creation proposal and allow commitment creation."""
    return CreationApprovalOutcome(status="approved", allow_create=True, proposal=proposal)


def reject_creation(proposal: CreationApprovalProposal) -> CreationApprovalOutcome:
    """Reject a creation proposal and block commitment creation."""
    return CreationApprovalOutcome(status="rejected", allow_create=False, proposal=proposal)


__all__ = [
    "CommitmentCreationSource",
    "CreationApprovalOutcome",
    "CreationApprovalProposal",
    "CreationAuthorityDecision",
    "approve_creation",
    "evaluate_creation_authority",
    "normalize_creation_source",
    "reject_creation",
    "resolve_autonomous_creation_threshold",
]
