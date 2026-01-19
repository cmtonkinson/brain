"""Default attention policy set for routing decisions."""

from __future__ import annotations

from attention.policy_schema import (
    AttentionPolicy,
    AuthorizationScope,
    PolicyOutcome,
    PolicyOutcomeKind,
    PolicyScope,
    PreferenceCondition,
    ScoreRange,
    UrgencyConstraint,
)


def default_attention_policies() -> list[AttentionPolicy]:
    """Return the baseline attention policies for routing."""
    return [
        AttentionPolicy(
            policy_id="always-notify-override",
            version="1.0.0",
            description="Always notify when an always-notify preference is set.",
            scope=PolicyScope(
                preferences=[PreferenceCondition(key="always_notify", value=True)],
            ),
            outcome=PolicyOutcome(kind=PolicyOutcomeKind.NOTIFY, channel="signal"),
        ),
        AttentionPolicy(
            policy_id="approval-requests-signal",
            version="1.0.0",
            description="Route approval requests via Signal by default.",
            scope=PolicyScope(
                signal_types={"approval.request"},
                authorization=AuthorizationScope(approval_statuses={"requested"}),
            ),
            outcome=PolicyOutcome(kind=PolicyOutcomeKind.NOTIFY, channel="signal"),
        ),
        AttentionPolicy(
            policy_id="quiet-hours-defer-low-urgency",
            version="1.0.0",
            description="Defer low or medium urgency during quiet hours.",
            scope=PolicyScope(
                urgency=UrgencyConstraint(levels={"low", "medium"}),
                preferences=[PreferenceCondition(key="quiet_hours", value=True)],
            ),
            outcome=PolicyOutcome(kind=PolicyOutcomeKind.DEFER),
        ),
        AttentionPolicy(
            policy_id="do-not-disturb-log-only-non-urgent",
            version="1.0.0",
            description="Log-only non-urgent signals during do-not-disturb windows.",
            scope=PolicyScope(
                urgency=UrgencyConstraint(levels={"low", "medium"}),
                preferences=[PreferenceCondition(key="do_not_disturb", value=True)],
            ),
            outcome=PolicyOutcome(kind=PolicyOutcomeKind.LOG_ONLY),
        ),
        AttentionPolicy(
            policy_id="high-urgency-notify-signal",
            version="1.0.0",
            description="Notify via Signal for high urgency and high confidence.",
            scope=PolicyScope(
                urgency=UrgencyConstraint(score=ScoreRange(minimum=0.85)),
                confidence=ScoreRange(minimum=0.85),
            ),
            outcome=PolicyOutcome(kind=PolicyOutcomeKind.NOTIFY, channel="signal"),
        ),
        AttentionPolicy(
            policy_id="low-urgency-high-cost-batch",
            version="1.0.0",
            description="Batch low urgency items with high channel cost.",
            scope=PolicyScope(
                urgency=UrgencyConstraint(levels={"low"}),
                channel_cost=ScoreRange(minimum=0.7),
            ),
            outcome=PolicyOutcome(kind=PolicyOutcomeKind.BATCH),
        ),
        AttentionPolicy(
            policy_id="long-form-analysis-to-obsidian",
            version="1.0.0",
            description="Route long-form analysis via Signal while other channels are unavailable.",
            scope=PolicyScope(
                signal_types={"analysis.ready", "analysis.summary", "analysis.report"},
            ),
            outcome=PolicyOutcome(kind=PolicyOutcomeKind.NOTIFY, channel="signal"),
        ),
    ]
