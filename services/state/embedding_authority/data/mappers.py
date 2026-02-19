"""Mapping helpers between SQL rows and EAS data-layer typed objects."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from packages.brain_shared.ids import require_ulid_bytes
from services.state.embedding_authority.data.types import EmbeddingAuditEntry


def row_to_audit_entry(row: Mapping[str, Any]) -> EmbeddingAuditEntry:
    """Convert a row mapping into an ``EmbeddingAuditEntry``."""
    occurred_at = row.get("occurred_at")
    if isinstance(occurred_at, datetime):
        normalized_occurred_at = (
            occurred_at
            if occurred_at.tzinfo is not None
            else occurred_at.replace(tzinfo=UTC)
        )
    else:
        normalized_occurred_at = datetime.now(UTC)

    return EmbeddingAuditEntry(
        id=require_ulid_bytes(row.get("id"), field_name="embedding_audit_log.id"),
        occurred_at=normalized_occurred_at,
        envelope_id=str(row.get("envelope_id", "")),
        trace_id=str(row.get("trace_id", "")),
        principal=str(row.get("principal", "")),
        operation=str(row.get("operation", "")),
        namespace=str(row.get("namespace", "")),
        key=str(row.get("key", "")),
        model=str(row.get("model", "")),
        outcome=str(row.get("outcome", "")),
        error_code=str(row.get("error_code", "")),
    )
