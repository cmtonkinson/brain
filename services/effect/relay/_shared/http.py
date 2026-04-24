"""HTTP request/response shape helpers shared by Relay inbound and outbound."""

from __future__ import annotations

from pydantic import BaseModel

from lib.shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from lib.shared.errors import ErrorDetail


class RequestMeta(BaseModel):
    """Shared inbound request metadata for Relay HTTP routes."""

    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""


class ErrorOut(BaseModel):
    """Stable serialized error shape for Relay HTTP responses."""

    code: str
    message: str
    category: str
    retryable: bool
    metadata: dict[str, str]


def meta_from_request(
    source: str,
    principal: str,
    trace_id: str | None,
    parent_id: str,
    envelope_id: str | None,
) -> EnvelopeMeta:
    """Build command metadata for one inbound Relay HTTP request."""
    meta = new_meta(
        kind=EnvelopeKind.COMMAND,
        source=source,
        principal=principal,
    )
    return EnvelopeMeta(
        envelope_id=envelope_id or meta.envelope_id,
        trace_id=trace_id or meta.trace_id,
        parent_id=parent_id,
        kind=EnvelopeKind.COMMAND,
        timestamp=meta.timestamp,
        source=source,
        principal=principal,
    )


def error_out(error: ErrorDetail) -> ErrorOut:
    """Normalize one service error into the shared HTTP error payload."""
    return ErrorOut(
        code=error.code,
        message=error.message,
        category=error.category.value,
        retryable=error.retryable,
        metadata=dict(error.metadata) if error.metadata else {},
    )
