"""Envelope metadata helpers for Brain SDK request envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class MetaOverrides:
    """Optional metadata overrides for one SDK call."""

    source: str | None = None
    principal: str | None = None
    trace_id: str | None = None
    parent_id: str = ""
    envelope_id: str | None = None
    timestamp: datetime | None = None


def build_envelope_meta(
    *,
    source: str,
    principal: str,
    trace_id: str | None = None,
    parent_id: str = "",
    envelope_id: str | None = None,
    timestamp: datetime | None = None,
) -> dict[str, object]:
    """Build one envelope metadata dict with sane SDK defaults."""
    ts = _normalize_utc(timestamp or datetime.now(UTC))
    return {
        "envelope_id": envelope_id or _new_id(),
        "trace_id": trace_id or _new_id(),
        "parent_id": parent_id,
        "kind": "command",
        "source": source,
        "principal": principal,
        "timestamp": ts.isoformat(),
    }


def _new_id() -> str:
    """Return one compact random identifier for envelope metadata."""
    return uuid4().hex


def _normalize_utc(value: datetime) -> datetime:
    """Normalize naive/aware datetimes to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
