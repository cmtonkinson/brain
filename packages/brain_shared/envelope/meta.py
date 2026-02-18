"""Envelope metadata primitives shared across Brain services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4


class EnvelopeKind(str, Enum):
    """Envelope kinds used for cross-service intent classification."""

    UNSPECIFIED = "unspecified"
    COMMAND = "command"
    EVENT = "event"
    RESULT = "result"
    STREAM = "stream"


@dataclass(frozen=True)
class EnvelopeMeta:
    """Canonical metadata attached to every envelope result."""

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
        envelope_id=envelope_id or _new_id(),
        trace_id=trace_id or _new_id(),
        parent_id=parent_id,
        timestamp=_utc_now() if timestamp is None else _normalize_utc(timestamp),
        kind=kind,
        source=source,
        principal=principal,
    )


def _new_id() -> str:
    """Return a compact random identifier."""
    return uuid4().hex


def _utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


def _normalize_utc(value: datetime) -> datetime:
    """Normalize naive/aware datetimes to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
