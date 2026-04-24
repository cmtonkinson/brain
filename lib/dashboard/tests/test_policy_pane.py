"""Tests for PolicyPane rendering logic."""

from __future__ import annotations

from datetime import datetime, timezone

from lib.dashboard.models.policy import (
    CurrentApprovalView,
    CurrentDecisionView,
    RecentPolicyItemView,
)
from lib.dashboard.panes.policy import PolicyPane


def _dt(h: int = 12, m: int = 0, s: int = 0) -> datetime:
    return datetime(2024, 1, 1, h, m, s, tzinfo=timezone.utc)


def test_policy_pane_no_data_renders_dash():
    pane = PolicyPane()
    text = pane._render_current()
    assert "—" in text


def test_policy_pane_approval_shown_when_present():
    approval = CurrentApprovalView(
        op_id="send-message-draft",
        summary="Draft a reply",
        actor="operator",
        channel="signal",
        requested_at=_dt(14, 31, 59),
        expires_at=_dt(14, 36, 59),
    )
    pane = PolicyPane(approval=approval)
    text = pane._render_current()
    assert "pending" in text
    assert "send-message-draft" in text
    assert "operator" in text


def test_policy_pane_decision_shown_when_no_approval():
    decision = CurrentDecisionView(
        op_id="op.search",
        actor="operator",
        channel="signal",
        state="allowed",
        decided_at=_dt(14, 31, 59),
    )
    pane = PolicyPane(decision=decision)
    text = pane._render_current()
    assert "allowed" in text
    assert "op.search" in text


def test_policy_pane_recent_rendered():
    recent = [
        RecentPolicyItemView(
            timestamp=_dt(14, 31, 58),
            state="allowed",
            op_id="cap.a",
        ),
        RecentPolicyItemView(
            timestamp=_dt(14, 32, 3),
            state="denied",
            op_id="cap.b",
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
        op_id="send-message-draft",
        summary="Draft",
        actor="operator",
        channel="signal",
        requested_at=_dt(14, 31, 0),
        expires_at=_dt(14, 36),
    )
    decision = CurrentDecisionView(
        op_id="cap.search",
        actor="operator",
        channel="signal",
        state="allowed",
        decided_at=_dt(14, 31, 59),
    )
    pane = PolicyPane(approval=approval, decision=decision)
    text = pane._render_current()
    assert "pending" in text
    assert "send-message-draft" in text
    assert "cap.search" not in text
