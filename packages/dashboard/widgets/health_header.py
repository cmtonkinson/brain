"""Dashboard header widget with one compact health/status line."""

from __future__ import annotations

from textual.widgets import Static

from packages.dashboard.data_sources import DockerDataSource, PostgresDataSource


class HealthHeader(Static):
    """Compact top-of-screen health bar."""

    _STATUS_ORDER = (
        "core",
        "agent",
        "postgres",
        "redis",
        "signal",
        "qdrant",
        "gateway",
    )

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
        statuses: dict[str, str] = {}
        for item in self._postgres.fetch_health_items():
            statuses[self._normalize_name(item.name)] = item.status
        for name, status in self._docker.fetch_container_statuses().items():
            statuses[self._normalize_name(name)] = status
        return "  ".join(
            self._format_status(name, statuses.get(name, "unknown"))
            for name in self._STATUS_ORDER
        )

    def _format_status(self, name: str, status: str) -> str:
        """Normalize one component name and render a compact colored status."""
        normalized_status = status.strip().lower()
        ok = normalized_status in {"ok", "healthy", "up", "running"}
        marker = "[green]OK[/green]" if ok else "[red]NOK[/red]"
        return f"{name} {marker}"

    def _normalize_name(self, name: str) -> str:
        """Normalize raw source-specific component names to header names."""
        normalized_name = name.strip().lower().removeprefix("brain-")
        aliases = {
            "pg": "postgres",
        }
        return aliases.get(normalized_name, normalized_name)
