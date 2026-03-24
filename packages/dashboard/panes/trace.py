"""Trace pane for active trace tree and timeline views."""

from __future__ import annotations

from packages.dashboard.data_sources import PostgresDataSource
from packages.dashboard.panes.base import DashboardPane


class TracePane(DashboardPane):
    """Pane showing the currently selected trace and timeline."""

    pane_title = "Trace"
    pane_id = "trace"
    toggle_key = "1"
    is_followable = True

    def __init__(self, *, postgres: PostgresDataSource | None = None, **kwargs) -> None:
        """Initialize the pane with one optional Postgres reader."""
        super().__init__(**kwargs)
        self._postgres = postgres or PostgresDataSource()

    def body_text(self) -> str:
        """Render one placeholder trace view."""
        trace = self._postgres.fetch_active_trace()
        event_lines = "\n".join(
            f"{event.timestamp}  {event.kind:<6} {event.name}" for event in trace.events
        )
        return (
            f"Trace: {trace.trace_id}\n"
            f"Title: {trace.title}\n"
            f"Current step: {trace.current_step}\n\n"
            "Timeline\n"
            f"{event_lines}"
        )
