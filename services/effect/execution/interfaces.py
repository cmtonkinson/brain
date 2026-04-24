"""Transport-neutral protocol interfaces for Execution Service."""

from __future__ import annotations

from typing import Protocol

from services.effect.execution.domain import (
    DynamicOpClassificationRow,
    OpDiscoveryStateRow,
    OpInvocationAuditRow,
)


class OpInvocationAuditRepository(Protocol):
    """Protocol for append-only Execution invocation audit persistence."""

    def append(self, *, row: OpInvocationAuditRow) -> None:
        """Persist one invocation audit row."""

    def count(self) -> int:
        """Return total persisted invocation audit row count."""


class OpDiscoveryStateRepository(Protocol):
    """Protocol for Execution-owned durable op discovery state."""

    def list_rows(self) -> tuple[OpDiscoveryStateRow, ...]:
        """Return all persisted discovery-state rows."""

    def upsert(self, *, row: OpDiscoveryStateRow) -> None:
        """Persist or replace one discovery-state row."""

    def delete(self, *, op_id: str) -> None:
        """Delete one discovery-state row by op id."""


class DynamicOpClassificationRepository(Protocol):
    """Protocol for persisted observed-definition and classification state."""

    def list_rows(self) -> tuple[DynamicOpClassificationRow, ...]:
        """Return all persisted dynamic op classification rows."""

    def upsert_observed(
        self, *, row: DynamicOpClassificationRow
    ) -> DynamicOpClassificationRow:
        """Persist the latest observed definition, resetting classification on digest change."""

    def get(self, *, op_id: str) -> DynamicOpClassificationRow | None:
        """Return one persisted row by op id."""

    def classify(
        self,
        *,
        op_id: str,
        definition_digest: str,
        effect: str | None = None,
        approval: str | None = None,
    ) -> DynamicOpClassificationRow:
        """Persist or update operator classification for one observed dynamic op.

        Either ``effect`` or ``approval`` may be omitted (``None``) to leave the
        existing persisted value unchanged. Passing both as ``None`` is invalid
        and raises ``ValueError``.
        """
