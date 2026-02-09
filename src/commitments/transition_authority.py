"""Authority evaluation for commitment state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from config import settings


@dataclass(frozen=True)
class TransitionAuthorityDecision:
    """Authority decision for a commitment state transition."""

    allow_transition: bool
    effective_confidence: float
    threshold: float
    reason: str


def evaluate_transition_authority(
    *,
    to_state: str,
    actor: Literal["user", "system"],
    confidence: float | None,
) -> TransitionAuthorityDecision:
    """Evaluate whether a transition can be applied autonomously."""
    threshold = settings.commitments.autonomous_transition_confidence_threshold
    if actor == "user":
        return TransitionAuthorityDecision(
            allow_transition=True,
            effective_confidence=1.0,
            threshold=threshold,
            reason="user_initiated",
        )
    if to_state == "MISSED":
        return TransitionAuthorityDecision(
            allow_transition=True,
            effective_confidence=1.0,
            threshold=threshold,
            reason="missed_is_autonomous",
        )
    if confidence is None:
        return TransitionAuthorityDecision(
            allow_transition=False,
            effective_confidence=0.0,
            threshold=threshold,
            reason="missing_confidence",
        )
    allow_transition = confidence >= threshold
    return TransitionAuthorityDecision(
        allow_transition=allow_transition,
        effective_confidence=confidence,
        threshold=threshold,
        reason="autonomy_confidence_gate",
    )


__all__ = ["TransitionAuthorityDecision", "evaluate_transition_authority"]
