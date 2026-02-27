"""Envelope metadata helpers for Brain SDK request envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from packages.brain_sdk._generated import envelope_pb2


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
) -> envelope_pb2.EnvelopeMeta:
    """Build one protobuf ``EnvelopeMeta`` with sane SDK defaults."""
    meta = envelope_pb2.EnvelopeMeta(
        envelope_id=envelope_id or _new_id(),
        trace_id=trace_id or _new_id(),
        parent_id=parent_id,
        kind=envelope_pb2.ENVELOPE_KIND_COMMAND,
        source=source,
        principal=principal,
    )
    meta.timestamp.FromDatetime(_normalize_utc(timestamp or datetime.now(UTC)))
    return meta


def timestamp_to_datetime(value: object) -> datetime:
    """Convert protobuf timestamp-like objects to UTC ``datetime`` values."""
    if hasattr(value, "ToDatetime"):
        return value.ToDatetime(tzinfo=UTC)
    raise TypeError("value does not support ToDatetime(tzinfo=...)")


def _new_id() -> str:
    """Return one compact random identifier for envelope metadata."""
    return uuid4().hex


def _normalize_utc(value: datetime) -> datetime:
    """Normalize naive/aware datetimes to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
