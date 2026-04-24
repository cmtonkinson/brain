"""Transport-neutral persistence interfaces for Language Service."""

from __future__ import annotations

from typing import Protocol

from services.effect.language.domain import (
    LanguageModelCallAuditRow,
    LanguageModelTurnCacheHopRow,
    TokenUsageTotals,
)


class LanguageModelCallAuditRepository(Protocol):
    """Protocol for append-only Language provider call audit persistence."""

    def append(self, *, row: LanguageModelCallAuditRow) -> LanguageModelCallAuditRow:
        """Persist one provider call audit row and return stored value."""

    def next_call_index(self, *, trace_id: str) -> int:
        """Return the next append-only call index for one trace."""

    def count(self) -> int:
        """Return total persisted provider call audit row count."""

    def sum_token_usage_by_trace(self, *, trace_id: str) -> TokenUsageTotals:
        """Return aggregate token totals across audited calls for one trace.

        Excludes ``outcome_kind == "error"`` rows so failed calls do not
        contaminate budget evaluation. Successful kinds (``final``,
        ``tool_call``, ``mixed``, ``empty``, ``embedding``) all contribute.
        """


class LanguageModelTurnCacheHopRepository(Protocol):
    """Protocol for append-only Language per-hop cache telemetry persistence."""

    def append(
        self, *, row: LanguageModelTurnCacheHopRow
    ) -> LanguageModelTurnCacheHopRow:
        """Persist one per-hop cache telemetry row and return stored value."""

    def next_hop_ordinal(self, *, trace_id: str) -> int:
        """Return the next chat-with-tools hop ordinal for one trace."""

    def count(self) -> int:
        """Return total persisted per-hop cache telemetry row count."""
