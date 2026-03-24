"""Textual application for the Brain Dashboard."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container

from packages.brain_dashboard.config import load_dashboard_config
from packages.brain_dashboard.widgets import HealthHeader, KeymapFooter
from packages.brain_dashboard.workspace import Workspace


class BrainDashboardApp(App[None]):
    """Out-of-band, read-only Brain observability dashboard."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #root {
        layout: vertical;
        height: 100%;
    }

    #health-header {
        dock: top;
        height: 1;
        padding: 0 1;
        background: $boost;
        color: $text;
    }

    #workspace {
        height: 1fr;
    }

    #keymap-footer {
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("1", "toggle_trace", "Trace"),
        Binding("2", "toggle_turn", "Turn"),
        Binding("3", "toggle_policy", "Policy"),
        Binding("4", "toggle_log", "Logs"),
        Binding("tab", "focus_next", "Focus Next"),
        Binding("enter", "toggle_maximize", "Maximize"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        """Initialize the dashboard app and config."""
        super().__init__()
        self._config = load_dashboard_config()

    def compose(self) -> ComposeResult:
        """Compose the dashboard chrome and workspace."""
        with Container(id="root"):
            yield HealthHeader()
            yield Workspace()
            yield KeymapFooter()

    def on_mount(self) -> None:
        """Set the terminal title once the app is mounted."""
        self.title = self._config.app_title

    def _workspace(self) -> Workspace:
        """Return the mounted workspace widget."""
        return self.query_one(Workspace)

    def action_toggle_trace(self) -> None:
        """Toggle the trace pane."""
        self._workspace().toggle_pane("trace")

    def action_toggle_turn(self) -> None:
        """Toggle the turn pane."""
        self._workspace().toggle_pane("turn")

    def action_toggle_policy(self) -> None:
        """Toggle the policy pane."""
        self._workspace().toggle_pane("policy")

    def action_toggle_log(self) -> None:
        """Toggle the log pane."""
        self._workspace().toggle_pane("log")

    def action_focus_next(self) -> None:
        """Move focus to the next visible pane."""
        self._workspace().focus_next_pane()

    def action_toggle_maximize(self) -> None:
        """Toggle maximized mode for the focused pane."""
        self._workspace().toggle_maximize_focused()
