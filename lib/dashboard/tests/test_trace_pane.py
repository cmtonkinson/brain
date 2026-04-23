"""Tests for TracePane pure-Python logic."""

from __future__ import annotations

from datetime import datetime, timezone

from lib.dashboard.models.trace import (
    TraceDetailView,
    TraceTreeNode,
    TraceTreeView,
)
from lib.dashboard.panes.trace import (
    TracePane,
    _node_label,
    _render_detail,
    _select_trace_view,
)


def _dt() -> datetime:
    return datetime(2024, 1, 1, 14, 31, 59, 21000, tzinfo=timezone.utc)


def _node(
    envelope_id: str = "E01",
    component: str = "agent",
    operation: str = "chat",
    status: str = "OK",
    source: str = "agent",
    parent_id: str | None = None,
    children: tuple = (),
) -> TraceTreeNode:
    return TraceTreeNode(
        envelope_id=envelope_id,
        component=component,
        operation=operation,
        status=status,
        source=source,
        principal="operator",
        timestamp=_dt(),
        parent_id=parent_id,
        elapsed_ms=2870,
        children=children,
        depth=0,
    )


def test_node_label_format():
    node = _node(
        component="lms", operation="chat_with_tools", status="OK", source="lms"
    )
    label = _node_label(node)
    assert "lms" in label
    assert "chat_with_tools" in label
    assert "OK" in label


def test_node_label_truncation():
    node = _node(
        component="a_very_long_component_name",
        operation="some_operation",
        source="a_very_long_source_name",
    )
    label = _node_label(node)
    assert len(label.split("  ")[0].rstrip()) <= 12


def test_render_detail_no_detail_view():
    node = _node()
    text = _render_detail(node)
    assert "Selected" in text
    assert "E01" in text
    assert "agent" in text
    assert "chat" in text
    assert "OK" in text


def test_render_detail_with_detail_view():
    node = _node(envelope_id="E02", component="lms", operation="chat", source="lms")
    detail = TraceDetailView(
        envelope_id="E02",
        component="language_model",
        operation="chat_with_tools",
        status="OK",
        source="lms",
        principal="operator",
        timestamp=_dt(),
        parent_id=None,
        elapsed_ms=2870,
        payload_summary="Tool-capable chat completion started.",
        errors=(),
    )
    text = _render_detail(node, detail)
    assert "Tool-capable" in text
    assert "none" in text


def test_render_detail_with_error():
    node = _node(envelope_id="E03")
    detail = TraceDetailView(
        envelope_id="E03",
        component="language_model",
        operation="chat",
        status="ERROR",
        source="lms",
        timestamp=_dt(),
        errors=("connection timeout",),
    )
    text = _render_detail(node, detail)
    assert "connection timeout" in text


def test_trace_pane_view_id():
    pane = TracePane()
    assert pane.view_id == "trace"


def test_tree_view_construction():
    child = _node(envelope_id="E02", parent_id="E01")
    root = _node(envelope_id="E01", children=(child,))
    tree_view = TraceTreeView(trace_id="T1", root_nodes=(root,), selected_node_id="E02")
    assert len(tree_view.root_nodes) == 1
    assert len(tree_view.root_nodes[0].children) == 1
    assert tree_view.selected_node_id == "E02"


def test_select_trace_view_prefers_most_recent_item():
    older = TraceTreeView(trace_id="older")
    newer = TraceTreeView(trace_id="newer")
    assert _select_trace_view([newer, older]) is newer
