"""Capability Engine audit repository implementations."""

from __future__ import annotations

from services.action.capability_engine.domain import CapabilityInvocationAuditRow
from services.action.capability_engine.interfaces import (
    CapabilityInvocationAuditRepository,
)


class InMemoryCapabilityInvocationAuditRepository(CapabilityInvocationAuditRepository):
    """Append-only in-memory invocation audit persistence for CES."""

    def __init__(self) -> None:
        self._rows: list[CapabilityInvocationAuditRow] = []

    def append(self, *, row: CapabilityInvocationAuditRow) -> None:
        """Persist one invocation audit row in append-only order."""
        self._rows.append(row)

    def count(self) -> int:
        """Return number of persisted invocation audit rows."""
        return len(self._rows)

    def list_rows(self) -> tuple[CapabilityInvocationAuditRow, ...]:
        """Expose immutable audit rows for tests and diagnostics."""
        return tuple(self._rows)
