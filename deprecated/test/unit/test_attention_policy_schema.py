"""Unit tests for attention policy schema validation."""

from datetime import time

import pytest
from pydantic import ValidationError

from attention.policy_schema import (
    AttentionPolicy,
    PolicyOutcome,
    PolicyOutcomeKind,
    PolicyScope,
    PreferenceCondition,
    ScoreRange,
    TimeWindow,
    UrgencyConstraint,
)


def test_policy_schema_accepts_valid_policy() -> None:
    """Ensure a valid policy schema parses successfully."""
    policy = AttentionPolicy(
        policy_id="quiet-hours-defer",
        version="1.0.0",
        description="Defer low-urgency signals during quiet hours.",
        scope=PolicyScope(
            signal_types={"reminder"},
            source_components={"scheduler"},
            urgency=UrgencyConstraint(levels={"low"}),
            confidence=ScoreRange(minimum=0.0, maximum=0.6),
            preferences=[PreferenceCondition(key="quiet_hours", value=True)],
            time_windows=[
                TimeWindow(
                    start=time(22, 0),
                    end=time(6, 0),
                    timezone="America/Los_Angeles",
                    days_of_week=[0, 1, 2, 3, 4, 5, 6],
                )
            ],
        ),
        outcome=PolicyOutcome(kind=PolicyOutcomeKind.DEFER),
    )

    assert policy.policy_id == "quiet-hours-defer"
    assert policy.scope.urgency is not None


def test_policy_schema_rejects_unknown_fields() -> None:
    """Ensure unknown fields fail validation."""
    with pytest.raises(ValidationError):
        AttentionPolicy.model_validate(
            {
                "policy_id": "unknown-field",
                "version": "1.0.0",
                "scope": {},
                "outcome": {"kind": "LOG_ONLY"},
                "unknown": "nope",
            }
        )


def test_policy_schema_requires_fields() -> None:
    """Ensure missing required fields fail validation."""
    with pytest.raises(ValidationError):
        AttentionPolicy.model_validate({"policy_id": "missing-fields"})
