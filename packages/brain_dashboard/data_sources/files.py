"""Read-only filesystem readers for dashboard support data."""

from __future__ import annotations


class FileDataSource:
    """Stub filesystem reader for log files and local diagnostics."""

    def list_known_log_files(self) -> tuple[str, ...]:
        """Return placeholder log file paths."""
        return ("logs/brain-core.log", "logs/brain-agent.log")
