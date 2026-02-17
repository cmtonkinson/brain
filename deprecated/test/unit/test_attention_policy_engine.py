"""Unit tests for attention policy evaluation."""

from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from attention.assessment_engine import BaseAssessmentOutcome
from attention.audit import AttentionAuditLogger
from attention.policy_engine import PolicyInputs, apply_policies
from attention.policy_schema import (
    AttentionPolicy,
    PolicyOutcome,
    PolicyOutcomeKind,
    PolicyScope,
    PreferenceCondition,
    ScoreRange,
    UrgencyConstraint,
)
from models import AttentionAuditLog


def _policy_inputs() -> PolicyInputs:
    """Build a baseline policy input payload."""
    return PolicyInputs(
        signal_reference="signal-1-reference",
        signal_type="signal-1",
        source_component="scheduler",
        urgency_level="high",
        urgency_score=0.9,
        confidence=0.8,
        channel_cost=0.4,
        preferences={"quiet_hours": False},
        timestamp=datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
    )


def test_matching_policy_returns_valid_outcome() -> None:
    """Ensure matching policies return valid outcomes."""
    policy = AttentionPolicy(
        policy_id="notify-high-urgency",
        version="1.0.0",
        scope=PolicyScope(
            signal_types={"signal-1"},
            source_components={"scheduler"},
            urgency=UrgencyConstraint(levels={"high"}),
            confidence=ScoreRange(minimum=0.7),
        ),
        outcome=PolicyOutcome(kind=PolicyOutcomeKind.NOTIFY, channel="signal"),
    )
    decision = apply_policies([policy], _policy_inputs(), BaseAssessmentOutcome.DEFER)

    assert decision.final_decision == "NOTIFY:signal"
    assert decision.policy_outcome == "NOTIFY:signal"
    assert decision.policy_explanation is not None


def test_invalid_policy_outcome_is_rejected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure invalid policy outcomes are rejected and logged."""
    policy = AttentionPolicy.model_construct(
        policy_id="invalid",
        version="1.0.0",
        scope=PolicyScope(),
        outcome=PolicyOutcome.model_construct(kind=PolicyOutcomeKind.NOTIFY, channel=None),
    )
    decision = apply_policies([policy], _policy_inputs(), BaseAssessmentOutcome.DEFER)

    assert decision.final_decision == BaseAssessmentOutcome.DEFER.value
    assert decision.policy_outcome is None
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_no_policy_match_falls_back_to_base() -> None:
    """Ensure no matching policy falls back to the base assessment."""
    policy = AttentionPolicy(
        policy_id="nope",
        version="1.0.0",
        scope=PolicyScope(signal_types={"other-signal"}),
        outcome=PolicyOutcome(kind=PolicyOutcomeKind.LOG_ONLY),
    )
    decision = apply_policies([policy], _policy_inputs(), BaseAssessmentOutcome.BATCH)

    assert decision.final_decision == BaseAssessmentOutcome.BATCH.value
    assert decision.policy_outcome is None


def test_preference_flag_matches_policy() -> None:
    """Ensure preference flags can trigger policy outcomes."""
    policy = AttentionPolicy(
        policy_id="always-notify",
        version="1.0.0",
        scope=PolicyScope(preferences=[PreferenceCondition(key="always_notify", value=True)]),
        outcome=PolicyOutcome(kind=PolicyOutcomeKind.NOTIFY, channel="signal"),
    )
    inputs = replace(
        _policy_inputs(),
        preferences={"quiet_hours": False, "always_notify": True},
    )

    decision = apply_policies([policy], inputs, BaseAssessmentOutcome.DEFER)

    assert decision.final_decision == "NOTIFY:signal"
    assert decision.policy_outcome == "NOTIFY:signal"


def test_routing_log_includes_assessment_policy_and_decision(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure routing logs include base assessment, policy, and final decision."""
    policy = AttentionPolicy(
        policy_id="notify-high-urgency",
        version="1.0.0",
        scope=PolicyScope(
            signal_types={"signal-1"},
            source_components={"scheduler"},
        ),
        outcome=PolicyOutcome(kind=PolicyOutcomeKind.LOG_ONLY),
    )
    session_factory = sqlite_session_factory
    with closing(session_factory()) as session:
        audit_logger = AttentionAuditLogger(session)
        decision = apply_policies(
            [policy],
            _policy_inputs(),
            BaseAssessmentOutcome.NOTIFY,
            audit_logger=audit_logger,
        )
        session.commit()

        record = session.query(AttentionAuditLog).first()

    assert decision.final_decision == "LOG_ONLY"
    assert record is not None
    assert record.base_assessment == BaseAssessmentOutcome.NOTIFY.value
    assert record.signal_reference == "signal-1-reference"
    assert record.policy_outcome == "LOG_ONLY"
    assert record.final_decision == "LOG_ONLY"
