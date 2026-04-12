"""Workspace widget: binary split tree layout engine and Textual renderer."""

from __future__ import annotations

from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget

from packages.dashboard.data_sources.logs import LogBuffer
from packages.dashboard.data_sources.policy import PolicyDataSource
from packages.dashboard.data_sources.traces import TraceDataSource
from packages.dashboard.data_sources.turns import TurnDataSource
from packages.dashboard.models.workspace import LayoutNode, WorkspaceState
from packages.dashboard.panes import LogPane, PolicyPane, TracePane, TurnPane
from packages.dashboard.panes.empty_picker import EmptyPicker


class DashboardDataSources:
    """Container for dashboard-wide data sources shared across panes."""

    def __init__(
        self,
        log_buffer: LogBuffer | None = None,
        turn_source: TurnDataSource | None = None,
        trace_source: TraceDataSource | None = None,
        policy_source: PolicyDataSource | None = None,
    ) -> None:
        self.log_buffer: LogBuffer = log_buffer if log_buffer is not None else LogBuffer()
        self.turn_source: TurnDataSource | None = turn_source
        self.trace_source: TraceDataSource | None = trace_source
        self.policy_source: PolicyDataSource | None = policy_source


class WorkspaceManager:
    """Pure-Python owner of WorkspaceState; all mutations produce new frozen instances."""

    def __init__(self) -> None:
        self._state: WorkspaceState = WorkspaceState(
            root=LayoutNode(pane_id="pane-0"),
            focused_pane_id="pane-0",
        )
        self._next_pane_id: int = 1

    @property
    def state(self) -> WorkspaceState:
        return self._state

    def _next_id(self) -> str:
        pid = f"pane-{self._next_pane_id}"
        self._next_pane_id += 1
        return pid

    def _find_node(
        self, pane_id: str, root: LayoutNode | None = None
    ) -> LayoutNode | None:
        """Recursively find leaf node by pane_id."""
        node = root if root is not None else self._state.root
        if node is None:
            return None
        if node.pane_id == pane_id:
            return node
        if node.children:
            left, right = node.children
            return self._find_node(pane_id, left) or self._find_node(pane_id, right)
        return None

    def _find_parent(
        self, pane_id: str, root: LayoutNode | None = None
    ) -> LayoutNode | None:
        """Recursively find parent of node with given pane_id."""
        node = root if root is not None else self._state.root
        if node is None or not node.children:
            return None
        left, right = node.children
        if left.pane_id == pane_id or right.pane_id == pane_id:
            return node
        return self._find_parent(pane_id, left) or self._find_parent(pane_id, right)

    def _leaves(self, node: LayoutNode | None = None) -> list[LayoutNode]:
        """Return all leaf LayoutNodes in tree order (left-to-right DFS)."""
        n = node if node is not None else self._state.root
        if n is None:
            return []
        if n.pane_id is not None:
            return [n]
        result: list[LayoutNode] = []
        if n.children:
            left, right = n.children
            result.extend(self._leaves(left))
            result.extend(self._leaves(right))
        return result

    def _replace_node(
        self, root: LayoutNode, target_id: str, replacement: LayoutNode
    ) -> LayoutNode:
        """Return new tree with the leaf at target_id replaced by replacement."""
        if root.pane_id == target_id:
            return replacement
        if not root.children:
            return root
        left, right = root.children
        new_left = self._replace_node(left, target_id, replacement)
        new_right = self._replace_node(right, target_id, replacement)
        return LayoutNode(split=root.split, children=(new_left, new_right))

    def _remove_node(self, root: LayoutNode, pane_id: str) -> LayoutNode:
        """Return new tree with leaf pane_id removed (parent collapsed to sibling)."""
        if not root.children:
            return root
        left, right = root.children
        if left.pane_id == pane_id:
            return right
        if right.pane_id == pane_id:
            return left
        new_left = self._remove_node(left, pane_id)
        new_right = self._remove_node(right, pane_id)
        return LayoutNode(split=root.split, children=(new_left, new_right))

    def find_node(self, pane_id: str) -> LayoutNode | None:
        """Public accessor for locating a leaf node by pane_id."""
        return self._find_node(pane_id)

    def split(self, orientation: Literal["horizontal", "vertical"]) -> str:
        """Split the focused pane. Returns new pane_id."""
        focused_id = self._state.focused_pane_id
        if focused_id is None:
            return ""
        focused = self._find_node(focused_id)
        if focused is None:
            return ""
        new_id = self._next_id()
        new_leaf = LayoutNode(pane_id=new_id)
        original = LayoutNode(pane_id=focused.pane_id, view_id=focused.view_id)
        branch = LayoutNode(split=orientation, children=(original, new_leaf))
        new_root = self._replace_node(self._state.root, focused_id, branch)
        self._state = self._state.model_copy(
            update={"root": new_root, "focused_pane_id": new_id}
        )
        return new_id

    def close_view(self) -> None:
        """Unload view from focused pane (set view_id=None)."""
        focused_id = self._state.focused_pane_id
        if focused_id is None:
            return
        focused = self._find_node(focused_id)
        if focused is None or focused.view_id is None:
            return
        cleared = LayoutNode(pane_id=focused.pane_id)
        new_root = self._replace_node(self._state.root, focused_id, cleared)
        self._state = self._state.model_copy(update={"root": new_root})

    def close_pane(self) -> None:
        """Remove focused pane from tree. If it's the last pane, do nothing."""
        focused_id = self._state.focused_pane_id
        if focused_id is None:
            return
        leaves = self._leaves()
        if len(leaves) <= 1:
            return
        new_root = self._remove_node(self._state.root, focused_id)
        remaining = self._leaves(new_root)
        new_focus = remaining[0].pane_id if remaining else None
        new_maximized = (
            self._state.maximized_pane_id
            if self._state.maximized_pane_id != focused_id
            else None
        )
        self._state = self._state.model_copy(
            update={
                "root": new_root,
                "focused_pane_id": new_focus,
                "maximized_pane_id": new_maximized,
            }
        )

    def maximize(self) -> None:
        """Toggle maximized_pane_id for focused pane."""
        focused_id = self._state.focused_pane_id
        new_max = None if self._state.maximized_pane_id == focused_id else focused_id
        self._state = self._state.model_copy(update={"maximized_pane_id": new_max})

    def focus_next(self) -> None:
        """Sequential focus: advance to next leaf in tree order."""
        leaves = self._leaves()
        if not leaves:
            return
        ids = [leaf.pane_id for leaf in leaves]
        focused_id = self._state.focused_pane_id
        if focused_id not in ids:
            new_focus = ids[0]
        else:
            idx = ids.index(focused_id)
            new_focus = ids[(idx + 1) % len(ids)]
        self._state = self._state.model_copy(update={"focused_pane_id": new_focus})

    def focus_previous(self) -> None:
        """Sequential focus: reverse direction."""
        leaves = self._leaves()
        if not leaves:
            return
        ids = [leaf.pane_id for leaf in leaves]
        focused_id = self._state.focused_pane_id
        if focused_id not in ids:
            new_focus = ids[-1]
        else:
            idx = ids.index(focused_id)
            new_focus = ids[(idx - 1) % len(ids)]
        self._state = self._state.model_copy(update={"focused_pane_id": new_focus})

    def load_view(self, view_id: str) -> None:
        """Set view_id on the focused leaf node."""
        focused_id = self._state.focused_pane_id
        if focused_id is None:
            return
        self.load_view_into(focused_id, view_id)

    def load_view_into(self, pane_id: str, view_id: str) -> None:
        """Set view_id on the leaf with the given pane_id without changing focus."""
        target = self._find_node(pane_id)
        if target is None:
            return
        updated = LayoutNode(pane_id=target.pane_id, view_id=view_id)
        new_root = self._replace_node(self._state.root, pane_id, updated)
        self._state = self._state.model_copy(update={"root": new_root})


class Workspace(Widget):
    """Textual widget that renders a binary split tree into nested containers."""

    DEFAULT_CSS = """
    Workspace { height: 1fr; }
    .split-container { height: 1fr; width: 1fr; }
    .pane-leaf {
        border: round $panel;
        padding: 0;
        height: 1fr;
        width: 1fr;
    }
    .pane-leaf.-focused {
        border: round $accent;
    }
    """

    def __init__(self, data_sources: DashboardDataSources | None = None) -> None:
        super().__init__(id="workspace")
        self.manager = WorkspaceManager()
        self._data_sources = data_sources if data_sources is not None else DashboardDataSources()

    def compose(self) -> ComposeResult:
        yield from self._render_node(self.manager.state.root)

    def _make_view(self, view_id: str, css_classes: str, node_id: str) -> Widget:
        """Instantiate a pane widget wired to the correct data source."""
        content_id = f"pane-content-{node_id}"
        if view_id == "log":
            return LogPane(
                buffer=self._data_sources.log_buffer,
                classes=css_classes,
                id=content_id,
            )
        if view_id == "trace":
            return TracePane(
                trace_source=self._data_sources.trace_source,
                classes=css_classes,
                id=content_id,
            )
        if view_id == "turn":
            return TurnPane(
                turn_source=self._data_sources.turn_source,
                classes=css_classes,
                id=content_id,
            )
        if view_id == "policy":
            return PolicyPane(
                policy_source=self._data_sources.policy_source,
                classes=css_classes,
                id=content_id,
            )
        # Unknown view id — fall back to empty picker.
        return EmptyPicker(is_sole=False, classes=css_classes, id=content_id)

    def _render_node(self, node: LayoutNode | None):  # type: ignore[return]
        """Recursively render split tree into Textual containers."""
        if node is None:
            return
        if node.children:
            left, right = node.children
            container_cls = Horizontal if node.split == "horizontal" else Vertical
            with container_cls(classes="split-container"):
                yield from self._render_node(left)
                yield from self._render_node(right)
        else:
            is_focused = node.pane_id == self.manager.state.focused_pane_id
            is_maximized = node.pane_id == self.manager.state.maximized_pane_id
            focused_class = "-focused" if is_focused else ""
            maximized_class = "-maximized" if is_maximized else ""
            css_classes = " ".join(
                c for c in ["pane-leaf", focused_class, maximized_class] if c
            )

            leaves = self.manager._leaves()
            is_sole = len(leaves) <= 1

            if node.view_id is not None:
                yield self._make_view(node.view_id, css_classes, node.pane_id)
            else:
                yield EmptyPicker(
                    is_sole=is_sole,
                    classes=css_classes,
                    id=f"pane-content-{node.pane_id}",
                )

    def _refresh(self) -> None:
        self.app.call_after_refresh(self.recompose)

    def split_horizontal(self) -> None:
        self.manager.split("horizontal")
        self._refresh()

    def split_vertical(self) -> None:
        self.manager.split("vertical")
        self._refresh()

    def close_view(self) -> None:
        self.manager.close_view()
        self._refresh()

    def close_pane(self) -> None:
        self.manager.close_pane()
        self._refresh()

    def maximize(self) -> None:
        self.manager.maximize()
        self._refresh()

    def focus_next(self) -> None:
        self.manager.focus_next()
        self._refresh()

    def focus_previous(self) -> None:
        self.manager.focus_previous()
        self._refresh()

    def load_view(self, pane_id: str, view_id: str) -> None:
        self.manager.load_view_into(pane_id, view_id)
        self._refresh()

    @property
    def focused_pane_id(self) -> str | None:
        return self.manager.state.focused_pane_id

    @property
    def focused_node_view_id(self) -> str | None:
        """view_id of the currently-focused leaf, or None."""
        focused = self.manager.state.focused_pane_id
        if focused is None:
            return None
        node = self.manager.find_node(focused)
        return node.view_id if node is not None else None
