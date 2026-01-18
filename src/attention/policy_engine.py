"""Policy evaluation for attention routing decisions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from attention.assessment_engine import BaseAssessmentOutcome
from attention.audit import AttentionAuditLogger
from attention.policy_schema import (
    AttentionPolicy,
    PolicyOutcomeKind,
    TimeWindow,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PolicyInputs:
    """Inputs used to evaluate a policy."""

    signal_type: str
    source_component: str
    urgency_level: str
    urgency_score: float
    confidence: float
    preferences: dict[str, str | int | bool | None]
    timestamp: datetime


@dataclass(frozen=True)
class RoutingDecision:
    """Outcome after applying policies to a base assessment."""

    base_assessment: BaseAssessmentOutcome
    policy_outcome: str | None
    final_decision: str
    policy_explanation: str | None


def apply_policies(
    policies: Iterable[AttentionPolicy],
    inputs: PolicyInputs,
    base_assessment: BaseAssessmentOutcome,
    audit_logger: AttentionAuditLogger | None = None,
) -> RoutingDecision:
    """Apply policies in order and return the routing decision."""
    for policy in policies:
        if not _policy_matches(policy, inputs):
            continue
        policy_outcome = _format_policy_outcome(policy)
        if policy_outcome is None:
            logger.error("Policy %s returned an invalid outcome.", policy.policy_id)
            return RoutingDecision(
                base_assessment=base_assessment,
                policy_outcome=None,
                final_decision=base_assessment.value,
                policy_explanation="invalid_policy_outcome",
            )
        decision = RoutingDecision(
            base_assessment=base_assessment,
            policy_outcome=policy_outcome,
            final_decision=policy_outcome,
            policy_explanation=f"policy={policy.policy_id} version={policy.version}",
        )
        if audit_logger:
            audit_logger.log_routing(
                source_component=inputs.source_component,
                signal_reference=inputs.signal_type,
                base_assessment=base_assessment.value,
                policy_outcome=policy_outcome,
                final_decision=decision.final_decision,
            )
        return decision

    return RoutingDecision(
        base_assessment=base_assessment,
        policy_outcome=None,
        final_decision=base_assessment.value,
        policy_explanation="no_policy_match",
    )


def _policy_matches(policy: AttentionPolicy, inputs: PolicyInputs) -> bool:
    """Return True when all policy criteria match the inputs."""
    scope = policy.scope
    if scope.signal_types and inputs.signal_type not in scope.signal_types:
        return False
    if scope.source_components and inputs.source_component not in scope.source_components:
        return False
    if scope.urgency:
        if scope.urgency.levels and inputs.urgency_level not in scope.urgency.levels:
            return False
        if scope.urgency.score and not _score_in_range(inputs.urgency_score, scope.urgency.score):
            return False
    if scope.confidence and not _score_in_range(inputs.confidence, scope.confidence):
        return False
    if scope.preferences:
        for pref in scope.preferences:
            if inputs.preferences.get(pref.key) != pref.value:
                return False
    if scope.time_windows and not _matches_time_window(scope.time_windows, inputs.timestamp):
        return False
    return True


def _score_in_range(value: float, score_range) -> bool:
    """Return True when a value falls within the score range."""
    if score_range.minimum is not None and value < score_range.minimum:
        return False
    if score_range.maximum is not None and value > score_range.maximum:
        return False
    return True


def _matches_time_window(time_windows: Iterable[TimeWindow], timestamp: datetime) -> bool:
    """Return True when the timestamp is within any of the time windows."""
    if timestamp.tzinfo is None:
        logger.warning("Naive timestamp provided for policy matching; assuming UTC.")
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    for window in time_windows:
        candidate = timestamp
        if window.timezone:
            try:
                candidate = timestamp.astimezone(ZoneInfo(window.timezone))
            except Exception:
                logger.error("Invalid timezone for policy window: %s", window.timezone)
                continue
        if window.days_of_week and candidate.weekday() not in window.days_of_week:
            continue
        if _time_in_window(candidate, window):
            return True
    return False


def _time_in_window(timestamp: datetime, window: TimeWindow) -> bool:
    """Return True when a timestamp's time falls within the window."""
    current = timestamp.timetz().replace(tzinfo=None)
    start = window.start
    end = window.end
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _format_policy_outcome(policy: AttentionPolicy) -> str | None:
    """Return a normalized policy outcome string or None on invalid."""
    outcome = policy.outcome
    if outcome.kind == PolicyOutcomeKind.NOTIFY:
        if not outcome.channel:
            return None
        return f"NOTIFY:{outcome.channel}"
    if outcome.kind == PolicyOutcomeKind.ESCALATE:
        if not outcome.channel:
            return None
        return f"ESCALATE:{outcome.channel}"
    if outcome.kind in {
        PolicyOutcomeKind.DROP,
        PolicyOutcomeKind.LOG_ONLY,
        PolicyOutcomeKind.DEFER,
        PolicyOutcomeKind.BATCH,
    }:
        return outcome.kind.value
    return None
