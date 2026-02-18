"""Convenience constructors for envelope results."""

from __future__ import annotations

from typing import Iterable, TypeVar

from packages.brain_shared.errors import ErrorDetail

from .meta import EnvelopeMeta
from .result import Result


T = TypeVar("T")


def success(*, meta: EnvelopeMeta, payload: T) -> Result[T]:
    """Build a successful result with payload and no errors."""
    return Result(metadata=meta, payload=payload, errors=[])


def failure(
    *,
    meta: EnvelopeMeta,
    errors: Iterable[ErrorDetail],
    payload: T | None = None,
) -> Result[T]:
    """Build a failed result with one or more errors."""
    return Result(metadata=meta, payload=payload, errors=list(errors))


def empty(*, meta: EnvelopeMeta) -> Result[None]:
    """Build an empty successful result."""
    return Result(metadata=meta, payload=None, errors=[])


def with_error(*, result: Result[T], error: ErrorDetail) -> Result[T]:
    """Return a new result with one additional error appended."""
    return Result(
        metadata=result.metadata,
        payload=result.payload,
        errors=[*result.errors, error],
    )
