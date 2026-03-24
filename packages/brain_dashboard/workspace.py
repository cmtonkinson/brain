"""Workspace widget for pane visibility, layout, and focus orchestration."""

from __future__ import annotations

from textual.containers import Container
from textual.reactive import reactive

from packages.brain_dashboard.panes import (
    DashboardPane,
    LogPane,
    PolicyPane,
    TracePane,
    TurnPane,
    WelcomePane,
)


class Workspace(Container):
    """Middle-of-screen workspace that owns visible panes and layout state."""

    DEFAULT_CSS = """
    Workspace {
        layout: grid;
        grid-size: 2 2;
        grid-columns: 2fr 1fr;
        grid-rows: 1fr 1fr;
        height: 1fr;
    }

    Workspace > DashboardPane {
        border: round $panel;
        padding: 1 2;
    }

    Workspace > DashboardPane.-maximized {
        column-span: 2;
        row-span: 2;
    }

    #pane-trace {
        column-span: 1;
        row-span: 2;
    }
    """

    maximized_pane_id = reactive("")

    def __init__(self) -> None:
        """Initialize the workspace with the default pane set."""
        super().__init__(id="workspace")
        self._panes: dict[str, DashboardPane] = {
            "welcome": WelcomePane(id="pane-welcome"),
            "trace": TracePane(id="pane-trace"),
            "turn": TurnPane(id="pane-turn"),
            "policy": PolicyPane(id="pane-policy"),
            "log": LogPane(id="pane-log"),
        }
        self._visible_pane_ids: list[str] = ["trace", "turn", "policy", "log"]
        self._focus_order: list[str] = ["trace", "turn", "policy", "log"]
        self._focused_pane_id = "trace"

    def compose(self):
        """Yield all panes once; visibility is controlled dynamically."""
        for pane in self._panes.values():
            yield pane

    def on_mount(self) -> None:
        """Apply initial visibility and focus state once mounted."""
        self.refresh_layout()

    def refresh_layout(self) -> None:
        """Apply pane visibility and maximized state to all mounted panes."""
        show_welcome = len(self._visible_pane_ids) == 0
        for pane_id, pane in self._panes.items():
            should_show = (
                pane_id == "welcome"
                if show_welcome
                else pane_id in self._visible_pane_ids
            )
            if should_show:
                pane.display = True
            else:
                pane.display = False

            if self.maximized_pane_id != "" and pane_id == self.maximized_pane_id:
                pane.add_class("-maximized")
            else:
                pane.remove_class("-maximized")

    def toggle_pane(self, pane_id: str) -> None:
        """Toggle one pane in or out of the visible workspace."""
        if pane_id not in self._panes or pane_id == "welcome":
            return
        if pane_id in self._visible_pane_ids:
            self._visible_pane_ids.remove(pane_id)
        else:
            self._visible_pane_ids.append(pane_id)
        if self._focused_pane_id not in self._visible_pane_ids:
            self._focused_pane_id = (
                self._visible_pane_ids[0] if self._visible_pane_ids else "welcome"
            )
        if (
            self.maximized_pane_id != ""
            and self.maximized_pane_id not in self._visible_pane_ids
        ):
            self.maximized_pane_id = ""
        self.refresh_layout()

    def focus_next_pane(self) -> None:
        """Move focus to the next visible pane."""
        visible = [
            pane_id
            for pane_id in self._focus_order
            if pane_id in self._visible_pane_ids
        ]
        if len(visible) == 0:
            self._focused_pane_id = "welcome"
            return
        if self._focused_pane_id not in visible:
            self._focused_pane_id = visible[0]
            return
        current_index = visible.index(self._focused_pane_id)
        self._focused_pane_id = visible[(current_index + 1) % len(visible)]

    def toggle_maximize_focused(self) -> None:
        """Toggle maximized mode for the currently focused pane."""
        pane_id = self._focused_pane_id
        if pane_id in ("", "welcome"):
            return
        self.maximized_pane_id = "" if self.maximized_pane_id == pane_id else pane_id
        self.refresh_layout()
