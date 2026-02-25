"""Transport-neutral protocol interfaces for Capability Engine Service."""

from __future__ import annotations

from typing import Protocol

from services.action.capability_engine.domain import CapabilityInvocationAuditRow


class CapabilityInvocationAuditRepository(Protocol):
    """Protocol for append-only Capability Engine invocation audit persistence."""

    def append(self, *, row: CapabilityInvocationAuditRow) -> None:
        """Persist one invocation audit row."""

    def count(self) -> int:
        """Return total persisted invocation audit row count."""
