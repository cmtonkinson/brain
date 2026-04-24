"""Envelope metadata primitives shared across Brain services."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict
from lib.shared.ids import generate_ulid_str


class EnvelopeKind(str, Enum):
    """Envelope kinds used for cross-service intent classification."""

    UNSPECIFIED = "unspecified"
    COMMAND = "command"
    EVENT = "event"
    RESULT = "result"
    STREAM = "stream"


class EnvelopeMeta(BaseModel):
    """Canonical metadata attached to every envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    envelope_id: str
    trace_id: str
    parent_id: str
    timestamp: datetime
    kind: EnvelopeKind
    source: str
    principal: str


def new_meta(
    *,
    kind: EnvelopeKind,
    source: str,
    principal: str,
    trace_id: str | None = None,
    parent_id: str = "",
    envelope_id: str | None = None,
    timestamp: datetime | None = None,
) -> EnvelopeMeta:
    """Build ``EnvelopeMeta`` with safe defaults for IDs and timestamp."""
    return EnvelopeMeta(
        envelope_id=envelope_id or generate_ulid_str(),
        trace_id=trace_id or generate_ulid_str(),
        parent_id=parent_id,
        timestamp=datetime.now(UTC) if timestamp is None else _normalize_utc(timestamp),
        kind=kind,
        source=source,
        principal=principal,
    )


def _normalize_utc(value: datetime) -> datetime:
    """Normalize naive/aware datetimes to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
