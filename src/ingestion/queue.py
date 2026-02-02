"""Background dispatch helpers for ingestion stage jobs."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from ingestion.schema import IngestionRequest

_STAGE1_TASK = "ingestion.stage1_store"
_STAGE2_TASK = "ingestion.stage2_extract"


def _get_celery_app():
    """Import the Celery app lazily to avoid import cycles."""
    from scheduler.celery_app import celery_app

    return celery_app


def enqueue_stage1_store(
    ingestion_id: UUID,
    request: IngestionRequest,
    *,
    send_task: Callable[..., object] | None = None,
) -> None:
    """Enqueue the Stage 1 store job for asynchronous execution."""
    payload = build_stage1_payload(ingestion_id=ingestion_id, request=request)
    sender = send_task or _get_celery_app().send_task
    sender(_STAGE1_TASK, args=(payload,))


def build_stage1_payload(
    *,
    ingestion_id: UUID,
    request: IngestionRequest,
) -> dict[str, object]:
    """Serialize a Stage 1 payload into a JSON-safe dict."""
    payload_b64 = None
    if request.payload is not None:
        payload_b64 = _encode_payload(request.payload)
    capture_time = _ensure_timezone(request.capture_time)
    return {
        "ingestion_id": str(ingestion_id),
        "payload_b64": payload_b64,
        "existing_object_key": request.existing_object_key,
        "source_type": request.source_type,
        "source_uri": request.source_uri,
        "source_actor": request.source_actor,
        "capture_time": capture_time.isoformat(),
        "mime_type": request.mime_type,
    }


def enqueue_stage2_extract(
    ingestion_id: UUID,
    *,
    send_task: Callable[..., object] | None = None,
) -> None:
    """Enqueue the Stage 2 extraction job for an ingestion."""
    payload = build_stage2_payload(ingestion_id=ingestion_id)
    sender = send_task or _get_celery_app().send_task
    sender(_STAGE2_TASK, args=(payload,))


def build_stage2_payload(*, ingestion_id: UUID) -> dict[str, object]:
    """Serialize a Stage 2 payload into a JSON-safe dict."""
    return {"ingestion_id": str(ingestion_id)}


def _encode_payload(payload: bytes | str) -> str:
    """Encode payload bytes or text into base64 for transport."""
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    elif isinstance(payload, bytes):
        raw = payload
    else:
        raise TypeError("payload must be bytes or UTF-8 text")
    return base64.b64encode(raw).decode("ascii")


def _ensure_timezone(value: datetime) -> datetime:
    """Normalize a datetime to UTC if timezone-aware."""
    if value.tzinfo is None:
        raise ValueError("capture_time must be timezone-aware")
    return value.astimezone(timezone.utc)
