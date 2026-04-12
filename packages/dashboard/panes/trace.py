"""Trace pane: envelope DAG tree and detail subview."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Static, Tree
from textual.widgets.tree import TreeNode

from packages.dashboard.data_sources.traces import TraceDataSource
from packages.dashboard.models.trace import (
    TraceDetailView,
    TraceTreeNode,
    TraceTreeView,
)
from packages.dashboard.panes.base import BaseView

_TRUNC = 24


def _node_label(node: TraceTreeNode) -> str:
    """Compact label: source  kind"""
    src = (node.source or "?")[:12]
    kind = (node.kind or "?")[:20]
    return f"{src:<12}  {kind}"


def _render_detail(node: TraceTreeNode, detail: TraceDetailView | None = None) -> str:
    """Render detail panel text for a selected tree node."""
    ts = node.timestamp.strftime("%H:%M:%S.%f")[:12]
    lines = [
        "Selected",
        "",
        f"Time       {ts}",
        f"Source     {node.source}",
        f"Kind       {node.kind}",
        f"Envelope   {node.envelope_id[:16]}...",
    ]
    if node.parent_id:
        lines.append(f"Parent     {node.parent_id[:16]}...")
    if detail is not None:
        if detail.component:
            lines.append(f"Component  {detail.component}")
        if detail.payload_summary:
            lines.append(f"Summary    {detail.payload_summary[:60]}")
        if detail.error:
            lines.append(f"Error      {detail.error[:60]}")
        else:
            lines.append("Errors     none")
    return "\n".join(lines)


class TracePane(BaseView):
    """Trace envelope DAG tree with detail subview."""

    view_id = "trace"
    view_title = "Trace"

    DEFAULT_CSS = """
    TracePane { layout: vertical; height: 1fr; }
    TracePane > #trace-tree { height: 1fr; }
    TracePane > #trace-detail { height: auto; max-height: 12; }
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("l", "expand_node", "Expand", show=False),
        Binding("h", "collapse_node", "Collapse", show=False),
    ]

    def __init__(
        self,
        trace_source: TraceDataSource | None = None,
        tree_view: TraceTreeView | None = None,
        details: dict[str, TraceDetailView] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._trace_source = trace_source
        self._tree_view = tree_view
        self._details: dict[str, TraceDetailView] = details or {}

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Tree("Trace", id="trace-tree")
            yield Static("", id="trace-detail")

    def on_mount(self) -> None:
        tree = self.query_one("#trace-tree", Tree)
        tree.root.expand()
        if self._tree_view is not None:
            self._populate_tree(tree)
        self.set_interval(2.0, self._refresh_from_source)

    def _refresh_from_source(self) -> None:
        if self._trace_source is None:
            return
        snapshot = self._trace_source.get_current()
        if snapshot is None or not snapshot.traces:
            return
        # Show all recent traces as root nodes in one combined tree
        combined_roots: list[TraceTreeNode] = []
        for tv in snapshot.traces:
            combined_roots.extend(tv.root_nodes)
        combined = TraceTreeView(
            trace_id="live",
            root_nodes=tuple(combined_roots),
        )
        self.refresh_data(combined)

    def _populate_tree(self, tree: Tree) -> None:
        tree.clear()
        if self._tree_view is None:
            return
        for root_node in self._tree_view.root_nodes:
            self._add_node(tree.root, root_node)

    def _add_node(self, parent: TreeNode, node: TraceTreeNode) -> TreeNode:
        label = _node_label(node)
        tree_node = parent.add(label, data=node, expand=True)
        for child in node.children:
            self._add_node(tree_node, child)
        return tree_node

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        node_data: TraceTreeNode | None = event.node.data
        if node_data is None:
            return
        detail = self._details.get(node_data.envelope_id)
        try:
            self.query_one("#trace-detail", Static).update(
                _render_detail(node_data, detail)
            )
        except Exception:
            pass

    def action_cursor_down(self) -> None:
        tree = self.query_one("#trace-tree", Tree)
        tree.action_cursor_down()

    def action_cursor_up(self) -> None:
        tree = self.query_one("#trace-tree", Tree)
        tree.action_cursor_up()

    def action_expand_node(self) -> None:
        tree = self.query_one("#trace-tree", Tree)
        if tree.cursor_node:
            tree.cursor_node.expand()

    def action_collapse_node(self) -> None:
        tree = self.query_one("#trace-tree", Tree)
        if tree.cursor_node:
            tree.cursor_node.collapse()

    def refresh_data(
        self,
        tree_view: TraceTreeView,
        details: dict[str, TraceDetailView] | None = None,
    ) -> None:
        self._tree_view = tree_view
        if details is not None:
            self._details = details
        try:
            tree = self.query_one("#trace-tree", Tree)
            self._populate_tree(tree)
        except Exception:
            pass
