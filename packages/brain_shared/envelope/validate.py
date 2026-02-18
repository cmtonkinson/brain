"""Validation and normalization helpers for envelope metadata."""

from __future__ import annotations

from datetime import UTC, datetime

from .meta import EnvelopeKind, EnvelopeMeta


def validate_meta(meta: EnvelopeMeta) -> None:
    """Validate required envelope metadata fields.

    Raises ``ValueError`` when required fields are missing.
    """
    if not meta.envelope_id:
        raise ValueError("metadata.envelope_id is required")
    if not meta.trace_id:
        raise ValueError("metadata.trace_id is required")
    if meta.timestamp is None:
        raise ValueError("metadata.timestamp is required")
    if meta.kind == EnvelopeKind.UNSPECIFIED:
        raise ValueError("metadata.kind must be specified")
    if not meta.source:
        raise ValueError("metadata.source is required")
    if not meta.principal:
        raise ValueError("metadata.principal is required")


def normalize_meta(meta: EnvelopeMeta) -> EnvelopeMeta:
    """Return a copy of metadata with UTC-normalized timestamp."""
    timestamp = meta.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    else:
        timestamp = timestamp.astimezone(UTC)

    if timestamp is meta.timestamp:
        return meta

    return EnvelopeMeta(
        envelope_id=meta.envelope_id,
        trace_id=meta.trace_id,
        parent_id=meta.parent_id,
        timestamp=timestamp,
        kind=meta.kind,
        source=meta.source,
        principal=meta.principal,
    )


def utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)
