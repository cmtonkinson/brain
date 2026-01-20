"""Celery callback bridge for scheduled execution callbacks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from scheduler.callback_bridge import (
    CallbackBridge,
    CallbackBridgeError,
    CallbackBridgeResult,
    DispatcherCallbackPayload,
)


@dataclass(frozen=True)
class CeleryCallbackRequest:
    """Celery callback payload for scheduled execution."""

    schedule_id: int
    scheduled_for: datetime | None
    correlation_id: str
    emitted_at: datetime
    provider_attempt: int = 1
    provider_task_id: str | None = None


def handle_celery_callback(
    request: CeleryCallbackRequest,
    bridge: CallbackBridge,
) -> CallbackBridgeResult:
    """Handle a Celery callback by translating and delegating to the bridge."""
    payload = translate_celery_callback(request)
    return bridge.handle_callback(payload)


def translate_celery_callback(request: CeleryCallbackRequest) -> DispatcherCallbackPayload:
    """Translate Celery callback request into dispatcher payload."""
    _validate_celery_request(request)
    scheduled_for = request.scheduled_for or request.emitted_at
    return DispatcherCallbackPayload(
        schedule_id=request.schedule_id,
        scheduled_for=_ensure_aware(scheduled_for),
        correlation_id=request.correlation_id,
        emitted_at=_ensure_aware(request.emitted_at),
    )


def _validate_celery_request(request: CeleryCallbackRequest) -> None:
    """Validate required Celery callback fields."""
    if request.schedule_id <= 0:
        raise CallbackBridgeError("schedule_id must be a positive integer.")
    if not request.correlation_id.strip():
        raise CallbackBridgeError("correlation_id is required.")
    _ensure_aware(request.emitted_at)
    if request.provider_attempt <= 0:
        raise CallbackBridgeError("provider_attempt must be >= 1.")


def _ensure_aware(value: datetime) -> datetime:
    """Ensure a datetime is timezone-aware, defaulting to UTC if naive."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
