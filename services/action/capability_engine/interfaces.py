"""Transport-neutral protocol interfaces for Capability Engine Service."""

from __future__ import annotations

from typing import Protocol

from services.action.capability_engine.domain import (
    CapabilityDiscoveryStateRow,
    CapabilityInvocationAuditRow,
)


class CapabilityInvocationAuditRepository(Protocol):
    """Protocol for append-only Capability Engine invocation audit persistence."""

    def append(self, *, row: CapabilityInvocationAuditRow) -> None:
        """Persist one invocation audit row."""

    def count(self) -> int:
        """Return total persisted invocation audit row count."""


class CapabilityDiscoveryStateRepository(Protocol):
    """Protocol for CES-owned durable capability discovery state."""

    def list_rows(self) -> tuple[CapabilityDiscoveryStateRow, ...]:
        """Return all persisted discovery-state rows."""

    def upsert(self, *, row: CapabilityDiscoveryStateRow) -> None:
        """Persist or replace one discovery-state row."""

    def delete(self, *, capability_id: str) -> None:
        """Delete one discovery-state row by capability id."""
