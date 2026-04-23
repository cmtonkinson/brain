"""Tests for TurnPane rendering logic."""

from __future__ import annotations

from datetime import datetime, timezone

from lib.dashboard.models.turn import CurrentTurnView, RecentTurnItemView
from lib.dashboard.panes.turn import TurnPane, _trunc


def _dt(h: int = 12, m: int = 0) -> datetime:
    return datetime(2024, 1, 1, h, m, 0, tzinfo=timezone.utc)


def _current(state: str = "complete", tokens: int | None = 1842) -> CurrentTurnView:
    return CurrentTurnView(
        state=state,
        inbound_content="Can you draft a reply to Chris about tomorrow?",
        inbound_time=_dt(14, 31),
        inbound_principal="operator",
        response_content=(
            "Sure. I've drafted a reply confirming tomorrow at 10am."
            if state == "complete"
            else None
        ),
        response_time=_dt(14, 32) if state == "complete" else None,
        model="claude-sonnet-4-20250514" if state == "complete" else None,
        provider="anthropic" if state == "complete" else None,
        reasoning_level="standard" if state == "complete" else None,
        token_count=tokens,
        trace_id="trace-1",
        elapsed_ms=2400 if state == "pending" else 1000,
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
    assert "Response" in text


def test_turn_pane_current_pending():
    pane = TurnPane(current=_current("pending", tokens=None))
    text = pane._render_current()
    assert "pending" in text
    assert "Tokens" not in text
    assert "Elapsed" in text
    assert "Response" not in text


def test_turn_pane_truncation():
    long_text = "x" * 100
    result = _trunc(long_text, 52)
    assert len(result) == 55
    assert result.endswith("...")


def test_turn_pane_no_truncation_short():
    result = _trunc("short", 52)
    assert result == "short"


def test_turn_pane_recent_rendered():
    recent = [
        RecentTurnItemView(
            timestamp=_dt(14, 28),
            direction="in",
            summary="Remind me about standup",
        )
    ]
    pane = TurnPane(recent=recent)
    text = pane._render_recent()
    assert "Recent" in text
    assert "Remind me" in text


def test_turn_pane_empty_recent():
    pane = TurnPane()
    assert pane._render_recent() == ""
