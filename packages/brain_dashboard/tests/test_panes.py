"""Tests for individual dashboard pane stubs."""

from __future__ import annotations

from packages.brain_dashboard.panes import (
    LogPane,
    PolicyPane,
    TracePane,
    TurnPane,
    WelcomePane,
)


def test_welcome_pane_renders_help_text() -> None:
    """Welcome pane should render the initial dashboard help text."""
    assert "Brain Dashboard" in WelcomePane().body_text()


def test_trace_pane_renders_stub_trace() -> None:
    """Trace pane should include the placeholder current-step line."""
    assert "Current step:" in TracePane().body_text()


def test_turn_pane_renders_stub_turn() -> None:
    """Turn pane should include the placeholder phase line."""
    assert "Phase:" in TurnPane().body_text()


def test_policy_pane_renders_stub_policy() -> None:
    """Policy pane should include the placeholder decision line."""
    assert "Decision:" in PolicyPane().body_text()


def test_log_pane_renders_stub_log_tail() -> None:
    """Log pane should include the placeholder log event content."""
    assert "switchboard accepted inbound signal message" in LogPane().body_text()
