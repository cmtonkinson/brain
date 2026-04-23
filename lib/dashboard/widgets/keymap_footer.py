"""Dashboard footer widget: width-adaptive keybinding reference."""

from __future__ import annotations

from dataclasses import dataclass

from lib.dashboard.models.workspace import WorkspaceState
from textual.widgets import Static


@dataclass
class FooterItem:
    """One keybinding hint shown in the footer."""

    key: str
    label: str
    priority: int  # 1=highest; higher number = dropped first when space constrained


_GLOBAL_ITEMS = [
    FooterItem("Q", "Quit", priority=1),
    FooterItem("enter", "Max", priority=2),
    FooterItem("tab", "Focus", priority=3),
    FooterItem("s", "Split-H", priority=4),
    FooterItem("v", "Split-V", priority=5),
    FooterItem("q", "Close Pane", priority=6),
]


def _format_item(item: FooterItem) -> str:
    return f"\\[{item.key}] {item.label}"


def build_footer_text(items: list[FooterItem], max_width: int) -> str:
    """Fit items into max_width, dropping lowest-priority items first."""
    sorted_items = sorted(items, key=lambda i: i.priority)
    rendered = [_format_item(i) for i in sorted_items]
    # try fitting all, then drop from end until it fits
    sep = "  "
    while rendered:
        line = sep.join(rendered)
        if len(line) <= max_width:
            return line
        rendered.pop()  # drop lowest-priority (last in sorted order)
    return ""


def build_global_items(
    workspace_state: WorkspaceState, focused_view_id: str | None
) -> list[FooterItem]:
    """Build the currently relevant global footer items from workspace state."""
    items = [FooterItem("Q", "Quit", priority=1)]
    if workspace_state.focused_pane_id is None:
        return items

    maximize_label = "Restore" if workspace_state.maximized_pane_id else "Max"
    close_label = "Close View" if focused_view_id is not None else "Close Pane"
    items.extend(
        [
            FooterItem("enter", maximize_label, priority=2),
            FooterItem("tab", "Focus", priority=3),
            FooterItem("s", "Split-H", priority=4),
            FooterItem("v", "Split-V", priority=5),
            FooterItem("q", close_label, priority=6),
        ]
    )
    return items


class KeymapFooter(Static):
    """Compact footer showing width-adapted global keybinding hints."""

    def __init__(self) -> None:
        super().__init__(id="keymap-footer", markup=True)
        self._items: list[FooterItem] = list(_GLOBAL_ITEMS)

    def on_mount(self) -> None:
        self.sync_from_app()

    def on_resize(self, event) -> None:
        del event
        self._rebuild()

    def sync_from_workspace(
        self, workspace_state: WorkspaceState, focused_view_id: str | None
    ) -> None:
        """Refresh footer items from the current workspace state."""
        self._items = build_global_items(workspace_state, focused_view_id)
        self._rebuild()

    def sync_from_app(self) -> None:
        """Refresh footer items by querying the mounted workspace widget."""
        try:
            from lib.dashboard.workspace import Workspace

            workspace = self.app.query_one(Workspace)
        except Exception:
            self._items = list(_GLOBAL_ITEMS)
            self._rebuild()
            return

        self.sync_from_workspace(
            workspace.manager.state, workspace.focused_node_view_id
        )

    def _rebuild(self) -> None:
        try:
            width = self.size.width or 80
        except Exception:
            width = 80
        self.update(build_footer_text(self._items, width))
