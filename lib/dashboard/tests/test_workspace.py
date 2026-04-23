"""Tests for WorkspaceManager binary split tree."""

from __future__ import annotations

from lib.dashboard.workspace import WorkspaceManager


def test_initial_state_single_pane():
    m = WorkspaceManager()
    leaves = m._leaves()
    assert len(leaves) == 1
    assert leaves[0].pane_id == "pane-0"
    assert m.state.focused_pane_id == "pane-0"


def test_split_horizontal_creates_two_leaves():
    m = WorkspaceManager()
    new_id = m.split("horizontal")
    leaves = m._leaves()
    assert len(leaves) == 2
    assert any(leaf.pane_id == new_id for leaf in leaves)


def test_split_vertical_creates_two_leaves():
    m = WorkspaceManager()
    m.split("vertical")
    leaves = m._leaves()
    assert len(leaves) == 2


def test_focus_next_cycles():
    m = WorkspaceManager()
    m.split("horizontal")
    first = m.state.focused_pane_id
    m.focus_next()
    second = m.state.focused_pane_id
    assert first != second
    m.focus_next()
    assert m.state.focused_pane_id == first


def test_close_view_clears_view_id():
    m = WorkspaceManager()
    m.load_view("trace")
    m.close_view()
    assert m.state.root.view_id is None


def test_close_pane_last_pane_does_nothing():
    m = WorkspaceManager()
    m.close_pane()
    assert len(m._leaves()) == 1


def test_close_pane_two_panes_leaves_one():
    m = WorkspaceManager()
    m.split("horizontal")
    m.close_pane()
    assert len(m._leaves()) == 1


def test_maximize_toggle():
    m = WorkspaceManager()
    m.maximize()
    assert m.state.maximized_pane_id == "pane-0"
    m.maximize()
    assert m.state.maximized_pane_id is None


def test_load_view_sets_view_id():
    m = WorkspaceManager()
    m.load_view("trace")
    assert m.state.root.view_id == "trace"
