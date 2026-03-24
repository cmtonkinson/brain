"""Read-only Docker inspection helpers for dashboard health state."""

from __future__ import annotations


class DockerDataSource:
    """Stub Docker reader for container and runtime status."""

    def fetch_container_statuses(self) -> dict[str, str]:
        """Return placeholder container statuses."""
        return {
            "brain-core": "healthy",
            "brain-agent": "healthy",
            "postgres": "healthy",
            "redis": "healthy",
            "signal": "healthy",
            "qdrant": "healthy",
            "gateway": "healthy",
        }
