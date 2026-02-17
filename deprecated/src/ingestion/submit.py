"""Submission service for ingestion intake requests."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from ingestion.errors import IngestionRequestRejected
from ingestion.schema import IngestionRequest, IngestionResponse, IngestionValidationError
from ingestion.schema import parse_ingestion_request
from models import Ingestion
from services.database import get_sync_session

UNKNOWN_SOURCE_TYPE = "unknown"


def submit_ingestion(
    payload: IngestionRequest | dict[str, Any],
    *,
    session_factory: Callable[[], Session] | None = None,
    now: datetime | None = None,
    enqueue_stage1: Callable[[UUID, IngestionRequest], None] | None = None,
) -> IngestionResponse:
    """Validate and persist an ingestion attempt, returning its identifier."""
    session_factory = session_factory or get_sync_session
    timestamp = now or datetime.now(timezone.utc)

    try:
        request = (
            payload if isinstance(payload, IngestionRequest) else parse_ingestion_request(payload)
        )
        _validate_submission_request(request)
    except IngestionValidationError as exc:
        ingestion_id = _persist_failed_ingestion(
            session_factory,
            payload,
            last_error=str(exc),
            created_at=timestamp,
        )
        raise IngestionRequestRejected(str(exc), ingestion_id) from exc

    with closing(session_factory()) as session:
        ingestion = Ingestion(
            source_type=request.source_type.strip(),
            source_uri=request.source_uri,
            source_actor=request.source_actor,
            created_at=timestamp,
            status="queued",
            last_error=None,
        )
        session.add(ingestion)
        session.commit()
        session.refresh(ingestion)
        response = IngestionResponse(ingestion_id=ingestion.id)

    if enqueue_stage1 is None:
        from ingestion.queue import enqueue_stage1_store

        enqueue_stage1 = enqueue_stage1_store
    enqueue_stage1(response.ingestion_id, request)
    return response


def _validate_submission_request(request: IngestionRequest) -> None:
    """Ensure the request is valid at submission time."""
    try:
        from ingestion.schema import validate_ingestion_request

        validate_ingestion_request(request)
    except IngestionValidationError as exc:
        raise IngestionValidationError(str(exc)) from exc


def _persist_failed_ingestion(
    session_factory: Callable[[], Session],
    payload: IngestionRequest | dict[str, Any],
    *,
    last_error: str,
    created_at: datetime,
) -> UUID:
    """Persist a failed ingestion attempt from a rejected submission."""
    source_type = _extract_source_field(payload, "source_type") or UNKNOWN_SOURCE_TYPE
    source_uri = _extract_source_field(payload, "source_uri")
    source_actor = _extract_source_field(payload, "source_actor")

    with closing(session_factory()) as session:
        ingestion = Ingestion(
            source_type=source_type,
            source_uri=source_uri,
            source_actor=source_actor,
            created_at=created_at,
            status="failed",
            last_error=last_error,
        )
        session.add(ingestion)
        session.commit()
        session.refresh(ingestion)
        return ingestion.id


def _extract_source_field(
    payload: IngestionRequest | dict[str, Any],
    key: str,
) -> str | None:
    """Extract optional source metadata fields from a payload."""
    if isinstance(payload, IngestionRequest):
        return getattr(payload, key, None)
    if isinstance(payload, dict):
        value = payload.get(key)
        if value is None:
            return None
        return str(value)
    return None
