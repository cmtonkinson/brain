"""Turn pane for current turn narrative and model context."""

from __future__ import annotations

from packages.dashboard.data_sources import PostgresDataSource
from packages.dashboard.panes.base import DashboardPane


class TurnPane(DashboardPane):
    """Pane showing a concise summary of the current agent turn."""

    pane_title = "Turn"
    pane_id = "turn"
    toggle_key = "2"

    def __init__(self, *, postgres: PostgresDataSource | None = None, **kwargs) -> None:
        """Initialize the pane with one optional Postgres reader."""
        super().__init__(**kwargs)
        self._postgres = postgres or PostgresDataSource()

    def body_text(self) -> str:
        """Render one placeholder turn summary."""
        turn = self._postgres.fetch_turn_view()
        return (
            f"Inbound: {turn.inbound_text}\n"
            f"Phase: {turn.phase}\n"
            f"Provider: {turn.provider}\n"
            f"Model: {turn.model_name}\n"
            f"Context turns: {turn.context_turn_count}\n"
            f"Summaries: {turn.summary_count}"
        )
