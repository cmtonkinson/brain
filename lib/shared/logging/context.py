"""Context propagation helpers for structured logging.

This module provides a process-local logging context built on ``contextvars`` so
request/correlation fields can be attached to every log line without manual
repetition. It is transport-agnostic and suitable for sync/async execution.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Mapping

_LOG_CONTEXT: ContextVar[dict[str, str]] = ContextVar("brain_log_context", default={})


def get_context() -> dict[str, str]:
    """Return a shallow copy of current logging context."""
    return dict(_LOG_CONTEXT.get())


def bind_context(**values: object) -> None:
    """Bind non-empty values into the current logging context.

    Values are stringified to maintain a stable structured log shape.
    ``None`` values are ignored.
    """
    if not values:
        return
    current = _LOG_CONTEXT.get().copy()
    for key, value in values.items():
        if value is None:
            continue
        current[str(key)] = str(value)
    _LOG_CONTEXT.set(current)


def clear_context(*keys: str) -> None:
    """Clear selected keys or the entire logging context."""
    if not keys:
        _LOG_CONTEXT.set({})
        return
    current = _LOG_CONTEXT.get().copy()
    for key in keys:
        current.pop(key, None)
    _LOG_CONTEXT.set(current)


@contextmanager
def log_context(values: Mapping[str, object]) -> Iterator[None]:
    """Temporarily bind logging context for the duration of a block."""
    token = _LOG_CONTEXT.set(_LOG_CONTEXT.get().copy())
    try:
        bind_context(**dict(values))
        yield
    finally:
        _LOG_CONTEXT.reset(token)
