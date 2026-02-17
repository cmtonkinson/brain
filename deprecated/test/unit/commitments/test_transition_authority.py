"""Unit tests for commitment transition authority evaluation."""

from __future__ import annotations

from config import settings
from commitments.transition_authority import evaluate_transition_authority


def test_system_missed_transition_is_allowed() -> None:
    """System MISSED transitions should bypass confidence gating."""
    decision = evaluate_transition_authority(
        to_state="MISSED",
        actor="system",
        confidence=None,
    )

    assert decision.allow_transition is True
    assert decision.reason == "missed_is_autonomous"


def test_user_transition_is_allowed() -> None:
    """User transitions should be allowed regardless of confidence."""
    decision = evaluate_transition_authority(
        to_state="COMPLETED",
        actor="user",
        confidence=0.1,
    )

    assert decision.allow_transition is True
    assert decision.reason == "user_initiated"


def test_system_transition_without_confidence_is_blocked() -> None:
    """System transitions without confidence should be blocked."""
    decision = evaluate_transition_authority(
        to_state="COMPLETED",
        actor="system",
        confidence=None,
    )

    assert decision.allow_transition is False
    assert decision.reason == "missing_confidence"


def test_system_transition_with_high_confidence_is_allowed() -> None:
    """System transitions with high confidence should be allowed."""
    decision = evaluate_transition_authority(
        to_state="COMPLETED",
        actor="system",
        confidence=0.95,
    )

    assert decision.allow_transition is True
    assert decision.effective_confidence == 0.95
    assert decision.reason == "autonomy_confidence_gate"


def test_system_transition_respects_configured_threshold(monkeypatch) -> None:
    """System transitions should use configured threshold comparison semantics."""
    monkeypatch.setattr(settings.commitments, "autonomous_transition_confidence_threshold", 0.9)

    blocked = evaluate_transition_authority(
        to_state="COMPLETED",
        actor="system",
        confidence=0.7,
    )
    allowed = evaluate_transition_authority(
        to_state="COMPLETED",
        actor="system",
        confidence=0.95,
    )

    assert blocked.allow_transition is False
    assert blocked.threshold == 0.9
    assert allowed.allow_transition is True
    assert allowed.threshold == 0.9
