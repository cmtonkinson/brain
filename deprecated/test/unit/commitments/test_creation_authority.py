"""Unit tests for commitment creation authority rules."""

from __future__ import annotations

import pytest

from commitments.creation_authority import (
    CommitmentCreationSource,
    approve_creation,
    evaluate_creation_authority,
    reject_creation,
    resolve_autonomous_creation_threshold,
)
from config import settings


def test_user_initiated_creation_is_approved() -> None:
    """User-initiated creation should bypass approval."""
    decision = evaluate_creation_authority(
        CommitmentCreationSource.USER,
        confidence=0.0,
        threshold=0.9,
    )

    assert decision.status == "approved"
    assert decision.allow_create is True
    assert decision.proposal is None


def test_agent_suggested_creation_requires_approval_below_threshold() -> None:
    """Agent suggestions below threshold should require approval."""
    decision = evaluate_creation_authority(
        CommitmentCreationSource.AGENT,
        confidence=0.0,
        threshold=0.9,
    )

    assert decision.status == "requires_approval"
    assert decision.allow_create is False
    assert decision.proposal is not None


def test_agent_suggested_creation_is_approved_above_threshold() -> None:
    """Agent suggestions above threshold should be approved."""
    decision = evaluate_creation_authority(
        CommitmentCreationSource.AGENT,
        confidence=0.95,
        threshold=0.9,
    )

    assert decision.status == "approved"
    assert decision.allow_create is True
    assert decision.proposal is None


def test_agent_suggested_defaults_to_zero_confidence() -> None:
    """Agent suggestions default to 0.0 confidence in v1."""
    decision = evaluate_creation_authority(CommitmentCreationSource.AGENT, threshold=0.9)

    assert decision.confidence == pytest.approx(0.0)
    assert decision.status == "requires_approval"


def test_approval_and_rejection_outcomes() -> None:
    """Approval outcomes should allow or block creation."""
    decision = evaluate_creation_authority(
        CommitmentCreationSource.AGENT,
        confidence=0.0,
        threshold=0.9,
    )
    assert decision.proposal is not None

    approved = approve_creation(decision.proposal)
    rejected = reject_creation(decision.proposal)

    assert approved.allow_create is True
    assert rejected.allow_create is False


def test_threshold_resolves_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configured thresholds should be used when not explicitly provided."""
    monkeypatch.setattr(settings.commitments, "autonomous_creation_confidence_threshold", 0.25)

    threshold = resolve_autonomous_creation_threshold()
    decision = evaluate_creation_authority(
        CommitmentCreationSource.AGENT,
        confidence=0.3,
    )

    assert threshold == pytest.approx(0.25)
    assert decision.threshold == pytest.approx(0.25)
    assert decision.status == "approved"
