"""Log pane for recent normalized log events."""

from __future__ import annotations

from packages.dashboard.data_sources import LogDataSource
from packages.dashboard.panes.base import DashboardPane


class LogPane(DashboardPane):
    """Pane showing a recent stream of structured log events."""

    pane_title = "Logs"
    pane_id = "log"
    toggle_key = "4"
    is_followable = True

    def __init__(self, *, logs: LogDataSource | None = None, **kwargs) -> None:
        """Initialize the pane with one optional log reader."""
        super().__init__(**kwargs)
        self._logs = logs or LogDataSource()

    def body_text(self) -> str:
        """Render one placeholder structured log tail."""
        return "\n".join(
            f"{event.timestamp} {event.level:<5} {event.message}"
            for event in self._logs.fetch_recent_events()
        )
