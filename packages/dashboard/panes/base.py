"""Base pane types shared by dashboard workspace panes."""

from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static


class DashboardPane(Static):
    """Common base widget for workspace panes."""

    pane_title = "Pane"
    pane_id = "pane"
    toggle_key = "0"
    is_followable = False

    focused = reactive(False)

    def __init__(self, *args, **kwargs) -> None:
        """Initialize the pane with standard Textual widget arguments."""
        super().__init__(*args, **kwargs)

    def render(self) -> str:
        """Render a simple titled body for the pane."""
        return f"[b]{self.pane_title}[/b]\n\n{self.body_text()}"

    def body_text(self) -> str:
        """Return pane-specific body text."""
        return "Stub pane."
