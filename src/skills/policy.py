"""Policy evaluation for skill invocation."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

from .registry_schema import AutonomyLevel
from .registry import OpRuntimeEntry, SkillRuntimeEntry

logger = logging.getLogger(__name__)


_AUTONOMY_ORDER = {
    AutonomyLevel.L0: 0,
    AutonomyLevel.L1: 1,
    AutonomyLevel.L2: 2,
    AutonomyLevel.L3: 3,
}


@dataclass(frozen=True)
class PolicyContext:
    """Inputs required to evaluate skill policy decisions."""

    actor: str | None = None
    channel: str | None = None
    allowed_capabilities: set[str] | None = None
    max_autonomy: AutonomyLevel | None = None
    confirmed: bool = False


@dataclass(frozen=True)
class PolicyDecision:
    """Policy evaluation result with reasons and metadata."""

    allowed: bool
    reasons: list[str]
    metadata: dict[str, str] = field(default_factory=dict)

    def log(self, skill: SkillRuntimeEntry | OpRuntimeEntry) -> None:
        """Emit a structured log entry for the policy decision."""
        logger.info(
            "policy decision",
            extra={
                "skill": skill.definition.name,
                "version": skill.definition.version,
                "allowed": self.allowed,
                "reasons": self.reasons,
                **self.metadata,
            },
        )


class PolicyEvaluator(Protocol):
    """Protocol for policy evaluators."""

    def evaluate(self, skill: SkillRuntimeEntry | OpRuntimeEntry, context: PolicyContext) -> PolicyDecision:
        """Evaluate policy for the given skill and context."""
        ...


class RateLimiter:
    """In-memory rate limiter for per-skill enforcement."""

    def __init__(self) -> None:
        """Initialize the rate limiter history."""
        self._history: dict[str, list[float]] = {}

    def allow(self, key: str, max_per_minute: int) -> bool:
        """Return True if a new request is allowed within the rate limit."""
        now = time.time()
        window_start = now - 60
        history = [ts for ts in self._history.get(key, []) if ts >= window_start]
        if len(history) >= max_per_minute:
            self._history[key] = history
            return False
        history.append(now)
        self._history[key] = history
        return True


class DefaultPolicy:
    """Default policy implementation for skills and ops."""

    def __init__(self) -> None:
        """Initialize the default policy evaluator."""
        self._rate_limiter = RateLimiter()

    def evaluate(self, skill: SkillRuntimeEntry | OpRuntimeEntry, context: PolicyContext) -> PolicyDecision:
        """Evaluate a skill against the default policy checks."""
        reasons: list[str] = []
        metadata = {
            "actor": context.actor or "",
            "channel": context.channel or "",
        }

        if skill.channels is not None:
            channel = context.channel
            if channel in skill.channels.deny:
                reasons.append("channel_denied")
            if skill.channels.allow and channel not in skill.channels.allow:
                reasons.append("channel_not_allowed")

        if skill.actors is not None:
            actor = context.actor
            if actor in skill.actors.deny:
                reasons.append("actor_denied")
            if skill.actors.allow and actor not in skill.actors.allow:
                reasons.append("actor_not_allowed")

        if context.allowed_capabilities is not None:
            missing = [
                cap
                for cap in skill.definition.capabilities
                if cap not in context.allowed_capabilities
            ]
            if missing:
                reasons.extend([f"capability_not_allowed:{cap}" for cap in missing])

        if context.max_autonomy is not None:
            if _AUTONOMY_ORDER[skill.autonomy] > _AUTONOMY_ORDER[context.max_autonomy]:
                reasons.append("autonomy_exceeds_limit")

        if skill.autonomy == AutonomyLevel.L0:
            reasons.append("autonomy_suggest_only")
        if skill.autonomy == AutonomyLevel.L1 and not context.confirmed:
            reasons.append("approval_required")

        if "requires_review" in skill.definition.policy_tags and not context.confirmed:
            reasons.append("review_required")

        if skill.rate_limit is not None:
            key = f"{skill.definition.name}@{skill.definition.version}"
            if not self._rate_limiter.allow(key, skill.rate_limit.max_per_minute):
                reasons.append("rate_limit_exceeded")

        decision = PolicyDecision(allowed=not reasons, reasons=reasons, metadata=metadata)
        decision.log(skill)
        return decision
