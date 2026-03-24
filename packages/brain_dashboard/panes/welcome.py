"""Welcome pane shown during startup and empty workspace states."""

from __future__ import annotations

from packages.brain_dashboard.panes.base import DashboardPane


class WelcomePane(DashboardPane):
    """Startup and empty-state pane for dashboard guidance."""

    pane_title = "Welcome"
    pane_id = "welcome"
    toggle_key = "0"

    def body_text(self) -> str:
        """Render the initial welcome and help text."""
        return (
            "Brain Dashboard\n\n"
            "Toggle panes with 1-4.\n"
            "Use Tab to cycle focus.\n"
            "Use Enter to maximize the focused pane.\n"
            "Use q to quit."
        )
