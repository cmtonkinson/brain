"""Tests for PolicyPane rendering logic."""

from __future__ import annotations

from datetime import datetime, timezone

from packages.dashboard.models.policy import (
    CurrentApprovalView,
    CurrentDecisionView,
    RecentPolicyItemView,
)
from packages.dashboard.panes.policy import PolicyPane


def _dt(h: int = 12, m: int = 0, s: int = 0) -> datetime:
    return datetime(2024, 1, 1, h, m, s, tzinfo=timezone.utc)


def test_policy_pane_no_data_renders_dash():
    pane = PolicyPane()
    text = pane._render_current()
    assert "—" in text


def test_policy_pane_approval_shown_when_present():
    approval = CurrentApprovalView(
        proposal_token="tok",
        capability_id="send-message-draft",
        summary="Draft a reply",
        actor="operator",
        channel="signal",
        expires_at=_dt(14, 36, 59),
    )
    pane = PolicyPane(approval=approval)
    text = pane._render_current()
    assert "pending" in text
    assert "send-message-draft" in text
    assert "operator" in text


def test_policy_pane_decision_shown_when_no_approval():
    decision = CurrentDecisionView(
        capability_id="capability.search",
        capability_version="1",
        autonomy_level="supervised",
        decision="allowed",
    )
    pane = PolicyPane(decision=decision)
    text = pane._render_current()
    assert "allowed" in text
    assert "capability.search" in text


def test_policy_pane_recent_rendered():
    recent = [
        RecentPolicyItemView(
            capability_id="cap.a",
            decision="allowed",
            allowed=True,
            decided_at=_dt(14, 31, 58),
        ),
        RecentPolicyItemView(
            capability_id="cap.b",
            decision="denied",
            allowed=False,
            decided_at=_dt(14, 32, 3),
        ),
    ]
    pane = PolicyPane(recent=recent)
    text = pane._render_recent()
    assert "Recent" in text
    assert "cap.a" in text
    assert "cap.b" in text


def test_policy_pane_empty_recent_renders_empty():
    pane = PolicyPane()
    assert pane._render_recent() == ""


def test_policy_pane_approval_takes_priority_over_decision():
    approval = CurrentApprovalView(
        proposal_token="tok",
        capability_id="send-message-draft",
        summary="Draft",
        actor="operator",
        channel="signal",
        expires_at=_dt(14, 36),
    )
    decision = CurrentDecisionView(
        capability_id="cap.search",
        capability_version="1",
        autonomy_level="supervised",
        decision="allowed",
    )
    pane = PolicyPane(approval=approval, decision=decision)
    text = pane._render_current()
    assert "pending" in text
    assert "send-message-draft" in text
    # decision should NOT appear since approval takes priority
    assert "cap.search" not in text
