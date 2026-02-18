"""Typed data models for EAS-owned Postgres records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EmbeddingAuditEntry:
    """Immutable audit-log record for EAS mutation/search operations."""

    id: bytes
    occurred_at: datetime
    envelope_id: str
    trace_id: str
    principal: str
    operation: str
    namespace: str
    key: str
    model: str
    outcome: str
    error_code: str
