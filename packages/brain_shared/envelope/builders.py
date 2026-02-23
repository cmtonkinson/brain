"""Convenience constructors for typed envelope responses."""

from __future__ import annotations

from typing import Iterable, TypeVar

from packages.brain_shared.errors import ErrorDetail

from .envelope import Envelope
from .meta import EnvelopeMeta
from .payload import Payload


T = TypeVar("T")


def success(*, meta: EnvelopeMeta, payload: T) -> Envelope[T]:
    """Build a successful envelope with payload and no errors."""
    return Envelope[T](
        metadata=meta,
        payload=Payload[T](value=payload),
        errors=[],
    )


def failure(
    *,
    meta: EnvelopeMeta,
    errors: Iterable[ErrorDetail],
    payload: T | None = None,
) -> Envelope[T]:
    """Build a failed envelope with one or more errors."""
    normalized_payload = None
    if payload is not None:
        normalized_payload = Payload[T](value=payload)
    return Envelope[T](metadata=meta, payload=normalized_payload, errors=list(errors))


def empty(*, meta: EnvelopeMeta) -> Envelope[None]:
    """Build an empty successful envelope."""
    return Envelope[None](metadata=meta, payload=None, errors=[])


def with_error(
    *,
    envelope: Envelope[T],
    error: ErrorDetail,
) -> Envelope[T]:
    """Return a new envelope with one additional error appended."""
    return Envelope[T](
        metadata=envelope.metadata,
        payload=envelope.payload,
        errors=[*envelope.errors, error],
    )
