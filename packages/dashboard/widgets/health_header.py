"""Dashboard header widget with one compact health/status line."""

from __future__ import annotations

from textual.widgets import Static

from packages.dashboard.data_sources import DockerDataSource, PostgresDataSource


class HealthHeader(Static):
    """Compact top-of-screen health bar."""

    def __init__(
        self,
        *,
        docker: DockerDataSource | None = None,
        postgres: PostgresDataSource | None = None,
    ) -> None:
        """Initialize the header with optional substrate readers."""
        super().__init__(id="health-header")
        self._docker = docker or DockerDataSource()
        self._postgres = postgres or PostgresDataSource()

    def on_mount(self) -> None:
        """Render the initial health text on mount."""
        self.update(self._build_text())

    def _build_text(self) -> str:
        """Build one compact health/status line."""
        items = [
            *(
                f"{item.name} {item.status}"
                for item in self._postgres.fetch_health_items()
            ),
            *(
                f"{name} {status}"
                for name, status in self._docker.fetch_container_statuses().items()
            ),
        ]
        return " | ".join(items)
