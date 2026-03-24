"""Read-only Redis access for dashboard state snapshots."""

from __future__ import annotations


class RedisDataSource:
    """Stub Redis reader for queue and cache observability."""

    def fetch_queue_depths(self) -> dict[str, int]:
        """Return placeholder queue depths."""
        return {"signal_inbound": 1, "approvals_pending": 0}
