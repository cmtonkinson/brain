"""Transport-neutral persistence interfaces for Language Model Service."""

from __future__ import annotations

from typing import Protocol

from services.action.language_model.domain import (
    LanguageModelCallAuditRow,
    LanguageModelTurnCacheHopRow,
)


class LanguageModelCallAuditRepository(Protocol):
    """Protocol for append-only LMS provider call audit persistence."""

    def append(self, *, row: LanguageModelCallAuditRow) -> LanguageModelCallAuditRow:
        """Persist one provider call audit row and return stored value."""

    def next_call_index(self, *, trace_id: str) -> int:
        """Return the next append-only call index for one trace."""

    def count(self) -> int:
        """Return total persisted provider call audit row count."""


class LanguageModelTurnCacheHopRepository(Protocol):
    """Protocol for append-only LMS per-hop cache telemetry persistence."""

    def append(
        self, *, row: LanguageModelTurnCacheHopRow
    ) -> LanguageModelTurnCacheHopRow:
        """Persist one per-hop cache telemetry row and return stored value."""

    def next_hop_ordinal(self, *, trace_id: str) -> int:
        """Return the next chat-with-tools hop ordinal for one trace."""
