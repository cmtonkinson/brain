"""Read-only log readers for the dashboard log pane."""

from __future__ import annotations

from packages.dashboard.models import DashboardLogEvent


class LogDataSource:
    """Stub log reader for normalized dashboard log events."""

    def fetch_recent_events(self) -> tuple[DashboardLogEvent, ...]:
        """Return placeholder recent log events."""
        return (
            DashboardLogEvent(
                timestamp="14:31:58",
                level="INFO",
                message="switchboard accepted inbound signal message",
            ),
            DashboardLogEvent(
                timestamp="14:31:59",
                level="INFO",
                message="public API invocation service_language_model",
            ),
        )
