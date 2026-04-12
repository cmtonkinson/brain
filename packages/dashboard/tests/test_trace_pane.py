"""Tests for TracePane pure-Python logic."""

from __future__ import annotations

from datetime import datetime, timezone

from packages.dashboard.models.trace import (
    TraceDetailView,
    TraceTreeNode,
    TraceTreeView,
)
from packages.dashboard.panes.trace import TracePane, _node_label, _render_detail


def _dt() -> datetime:
    return datetime(2024, 1, 1, 14, 31, 59, 21000, tzinfo=timezone.utc)


def _node(
    envelope_id: str = "E01",
    kind: str = "chat",
    source: str = "agent",
    parent_id: str | None = None,
    children: tuple = (),
) -> TraceTreeNode:
    return TraceTreeNode(
        envelope_id=envelope_id,
        kind=kind,
        source=source,
        timestamp=_dt(),
        parent_id=parent_id,
        children=children,
        depth=0,
    )


def test_node_label_format():
    node = _node(kind="chat_with_tools", source="lms")
    label = _node_label(node)
    assert "lms" in label
    assert "chat_with_tools" in label


def test_node_label_truncation():
    node = _node(source="a_very_long_source_name", kind="some_operation")
    label = _node_label(node)
    # source truncated to 12 chars
    assert len(label.split("  ")[0].rstrip()) <= 12


def test_render_detail_no_detail_view():
    node = _node()
    text = _render_detail(node)
    assert "Selected" in text
    assert "E01" in text
    assert "agent" in text
    assert "chat" in text


def test_render_detail_with_detail_view():
    node = _node(envelope_id="E02", kind="chat", source="lms")
    detail = TraceDetailView(
        envelope_id="E02",
        kind="chat",
        source="lms",
        component="language_model",
        timestamp=_dt(),
        payload_summary="Tool-capable chat completion started.",
        error=None,
    )
    text = _render_detail(node, detail)
    assert "language_model" in text
    assert "Tool-capable" in text
    assert "none" in text  # errors=none


def test_render_detail_with_error():
    node = _node(envelope_id="E03")
    detail = TraceDetailView(
        envelope_id="E03",
        kind="chat",
        source="lms",
        timestamp=_dt(),
        error="connection timeout",
    )
    text = _render_detail(node, detail)
    assert "connection timeout" in text


def test_trace_pane_view_id():
    pane = TracePane()
    assert pane.view_id == "trace"


def test_tree_view_construction():
    child = _node(envelope_id="E02", parent_id="E01")
    root = _node(envelope_id="E01", children=(child,))
    tv = TraceTreeView(trace_id="T1", root_nodes=(root,))
    assert len(tv.root_nodes) == 1
    assert len(tv.root_nodes[0].children) == 1
