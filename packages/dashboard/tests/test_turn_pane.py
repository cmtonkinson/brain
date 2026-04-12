"""Tests for TurnPane rendering logic."""

from __future__ import annotations

from datetime import datetime, timezone

from packages.dashboard.models.turn import CurrentTurnView, RecentTurnItemView
from packages.dashboard.panes.turn import TurnPane, _trunc


def _dt(h: int = 12, m: int = 0) -> datetime:
    return datetime(2024, 1, 1, h, m, 0, tzinfo=timezone.utc)


def _current(phase: str = "complete", tokens: int | None = 1842) -> CurrentTurnView:
    return CurrentTurnView(
        session_id="sess-1",
        inbound_text="Can you draft a reply to Chris about tomorrow?",
        phase=phase,
        model_name="claude-sonnet-4-20250514",
        provider="anthropic",
        context_turn_count=3,
        summary_count=0,
        token_count=tokens,
    )


def test_turn_pane_no_data_renders_dash():
    pane = TurnPane()
    text = pane._render_current()
    assert "—" in text


def test_turn_pane_current_complete():
    pane = TurnPane(current=_current("complete"))
    text = pane._render_current()
    assert "complete" in text
    assert "anthropic" in text
    assert "1842" in text


def test_turn_pane_current_pending():
    pane = TurnPane(current=_current("pending", tokens=None))
    text = pane._render_current()
    assert "pending" in text
    assert "Tokens" not in text


def test_turn_pane_truncation():
    long_text = "x" * 100
    result = _trunc(long_text, 52)
    assert len(result) == 55  # 52 + "..."
    assert result.endswith("...")


def test_turn_pane_no_truncation_short():
    result = _trunc("short", 52)
    assert result == "short"


def test_turn_pane_recent_rendered():
    recent = [
        RecentTurnItemView(
            turn_id="t1",
            session_id="s1",
            inbound_preview="Remind me about standup",
            phase="complete",
            model_name="claude-sonnet-4",
            recorded_at=_dt(14, 28),
        )
    ]
    pane = TurnPane(recent=recent)
    text = pane._render_recent()
    assert "Recent" in text
    assert "Remind me" in text


def test_turn_pane_empty_recent():
    pane = TurnPane()
    assert pane._render_recent() == ""
