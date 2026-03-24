"""Tests for dashboard workspace pane orchestration."""

from __future__ import annotations

from packages.brain_dashboard.workspace import Workspace


def test_toggle_pane_hides_visible_pane() -> None:
    """Workspace should remove a pane from the visible set when toggled off."""
    workspace = Workspace()

    workspace.toggle_pane("trace")

    assert "trace" not in workspace._visible_pane_ids


def test_toggle_pane_shows_hidden_pane() -> None:
    """Workspace should re-add a pane to the visible set when toggled on."""
    workspace = Workspace()
    workspace.toggle_pane("trace")

    workspace.toggle_pane("trace")

    assert "trace" in workspace._visible_pane_ids


def test_focus_next_pane_cycles_visible_panes() -> None:
    """Workspace should cycle focus through visible panes."""
    workspace = Workspace()

    workspace.focus_next_pane()

    assert workspace._focused_pane_id == "turn"
