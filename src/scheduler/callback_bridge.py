"""Callback bridge for scheduler provider callbacks."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from sqlalchemy.orm import Session

from scheduler import data_access


class CallbackBridgeError(ValueError):
    """Raised when callback payload validation fails."""


@dataclass(frozen=True)
class DispatcherCallbackPayload:
    """Provider-agnostic payload sent to the dispatcher entrypoint."""

    schedule_id: int
    scheduled_for: datetime
    trace_id: str
    emitted_at: datetime
    trigger_source: str = "scheduler_callback"


@dataclass(frozen=True)
class CallbackBridgeResult:
    """Outcome of handling a scheduler callback."""

    status: str
    duplicate_execution_id: int | None = None


class DispatcherEntrypoint(Protocol):
    """Protocol for dispatcher entrypoint implementations."""

    def dispatch(self, payload: DispatcherCallbackPayload) -> None:
        """Dispatch the callback payload to the scheduler dispatcher."""
        ...


class CallbackBridge:
    """Translate provider callbacks into dispatcher invocations with idempotency."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        dispatcher: DispatcherEntrypoint,
    ) -> None:
        """Initialize the callback bridge with persistence and dispatcher access."""
        self._session_factory = session_factory
        self._dispatcher = dispatcher

    def handle_callback(self, payload: DispatcherCallbackPayload) -> CallbackBridgeResult:
        """Validate a callback payload, enforce idempotency, and invoke dispatcher."""
        _validate_payload(payload)
        with closing(self._session_factory()) as session:
            existing = data_access.get_execution_by_trace_id(
                session,
                payload.schedule_id,
                payload.trace_id,
            )
        if existing is not None:
            return CallbackBridgeResult(
                status="duplicate",
                duplicate_execution_id=existing.id,
            )
        self._dispatcher.dispatch(payload)
        return CallbackBridgeResult(status="accepted")


def _validate_payload(payload: DispatcherCallbackPayload) -> None:
    """Validate callback payload fields before dispatch."""
    if payload.schedule_id <= 0:
        raise CallbackBridgeError("schedule_id must be a positive integer.")
    if not payload.trace_id.strip():
        raise CallbackBridgeError("trace_id is required.")
    if not payload.trigger_source.strip():
        raise CallbackBridgeError("trigger_source is required.")
    payload_scheduled = _ensure_aware(payload.scheduled_for)
    payload_emitted = _ensure_aware(payload.emitted_at)
    if (
        payload_scheduled > payload_emitted
        and (payload_scheduled - payload_emitted).total_seconds() > 86400
    ):
        raise CallbackBridgeError("scheduled_for is too far ahead of emitted_at.")


def _ensure_aware(value: datetime) -> datetime:
    """Ensure a datetime is timezone-aware, defaulting to UTC if naive."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
