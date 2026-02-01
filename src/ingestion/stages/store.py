"""Stage 1 store runner for raw ingestion artifacts."""

from __future__ import annotations

from contextlib import closing
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from config import settings
from ingestion.provenance import ProvenanceSourceInput, record_provenance
from ingestion.store import _checksum_from_object_key, store_raw_artifact
from models import Artifact, IngestionArtifact
from services.database import get_sync_session
from services.object_store import ObjectStore


@dataclass(frozen=True)
class Stage1StoreRequest:
    """Normalized Stage 1 store request payload."""

    ingestion_id: UUID
    payload: bytes | None
    existing_object_key: str | None
    source_type: str
    source_uri: str | None
    source_actor: str | None
    capture_time: datetime
    mime_type: str | None


@dataclass(frozen=True)
class Stage1StoreResult:
    """Outcome summary for Stage 1 store execution."""

    status: str
    object_key: str | None
    error: str | None


def run_stage1_store(
    request: Stage1StoreRequest,
    *,
    session_factory: Callable[[], Session] | None = None,
    object_store: ObjectStore | None = None,
    now: datetime | None = None,
) -> Stage1StoreResult:
    """Execute Stage 1 store for raw artifacts with dedupe semantics."""
    session_factory = session_factory or get_sync_session
    store = object_store or ObjectStore(settings.objects.root_dir)
    timestamp = now or datetime.now(timezone.utc)
    ingested_at = _ensure_timezone(request.capture_time)

    if request.payload is None and request.existing_object_key is None:
        raise ValueError("Stage 1 store requires payload or existing_object_key")
    if request.payload is not None and request.existing_object_key is not None:
        raise ValueError("Stage 1 store cannot accept both payload and existing_object_key")

    status: str
    object_key: str | None = None
    error: str | None = None

    if request.payload is not None:
        result = store_raw_artifact(
            request.payload,
            mime_type=request.mime_type,
            ingested_at=ingested_at,
            session_factory=session_factory,
            object_store=store,
        )
        object_key = result.object_key
        if result.created:
            status = "success"
        else:
            status = "skipped"
            error = "raw artifact already exists"
    else:
        object_key = request.existing_object_key
        if object_key is None:
            raise ValueError("existing_object_key must be provided when payload is absent")
        try:
            data = store.read(object_key)
        except (FileNotFoundError, ValueError):
            status = "failed"
            error = f"raw artifact not found for object_key: {object_key}"
            return _record_stage_outcome(
                session_factory=session_factory,
                ingestion_id=request.ingestion_id,
                object_key=None,
                status=status,
                error=error,
                created_at=timestamp,
            )
        _ensure_artifact_for_existing_key(
            session_factory=session_factory,
            object_key=object_key,
            payload=data,
            mime_type=request.mime_type,
            ingested_at=ingested_at,
            created_at=timestamp,
        )
        status = "success"

    result = _record_stage_outcome(
        session_factory=session_factory,
        ingestion_id=request.ingestion_id,
        object_key=object_key,
        status=status,
        error=error,
        created_at=timestamp,
    )

    if status in {"success", "skipped"} and object_key is not None:
        sources = [
            ProvenanceSourceInput(
                source_type=request.source_type,
                source_uri=request.source_uri,
                source_actor=request.source_actor,
                captured_at=ingested_at,
            )
        ]
        with closing(session_factory()) as session:
            record_provenance(
                session,
                object_key=object_key,
                ingestion_id=request.ingestion_id,
                sources=sources,
                now=timestamp,
            )
            session.commit()

    return result


def parse_stage1_payload(payload: dict[str, object]) -> Stage1StoreRequest:
    """Parse a Stage 1 payload from a JSON-safe dictionary."""
    ingestion_id_raw = payload.get("ingestion_id")
    if not isinstance(ingestion_id_raw, str):
        raise ValueError("ingestion_id is required for Stage 1 payload")
    payload_b64 = payload.get("payload_b64")
    payload_bytes = _decode_payload(payload_b64)
    existing_object_key = payload.get("existing_object_key")
    if existing_object_key is not None:
        existing_object_key = str(existing_object_key)
    capture_time_raw = payload.get("capture_time")
    capture_time = _parse_datetime(capture_time_raw)
    source_type = payload.get("source_type")
    if not isinstance(source_type, str):
        raise ValueError("source_type is required for Stage 1 payload")
    return Stage1StoreRequest(
        ingestion_id=UUID(ingestion_id_raw),
        payload=payload_bytes,
        existing_object_key=existing_object_key,
        source_type=source_type,
        source_uri=_optional_text(payload.get("source_uri")),
        source_actor=_optional_text(payload.get("source_actor")),
        capture_time=capture_time,
        mime_type=_optional_text(payload.get("mime_type")),
    )


def _record_stage_outcome(
    *,
    session_factory: Callable[[], Session],
    ingestion_id: UUID,
    object_key: str | None,
    status: str,
    error: str | None,
    created_at: datetime,
) -> Stage1StoreResult:
    """Persist Stage 1 outcome to ingestion_artifacts."""
    with closing(session_factory()) as session:
        existing = (
            session.query(IngestionArtifact)
            .filter(
                IngestionArtifact.ingestion_id == ingestion_id,
                IngestionArtifact.stage == "store",
                IngestionArtifact.object_key == object_key,
            )
            .first()
        )
        if existing is None and object_key is None:
            existing = (
                session.query(IngestionArtifact)
                .filter(
                    IngestionArtifact.ingestion_id == ingestion_id,
                    IngestionArtifact.stage == "store",
                    IngestionArtifact.object_key.is_(None),
                )
                .first()
            )
        if existing is not None:
            return Stage1StoreResult(
                status=str(existing.status),
                object_key=existing.object_key,
                error=existing.error,
            )

        record = IngestionArtifact(
            ingestion_id=ingestion_id,
            stage="store",
            object_key=object_key,
            created_at=created_at,
            status=status,
            error=error,
        )
        session.add(record)
        session.commit()
    return Stage1StoreResult(status=status, object_key=object_key, error=error)


def _ensure_artifact_for_existing_key(
    *,
    session_factory: Callable[[], Session],
    object_key: str,
    payload: bytes,
    mime_type: str | None,
    ingested_at: datetime,
    created_at: datetime,
) -> None:
    """Create or update artifact metadata for an existing object key."""
    checksum = _checksum_from_object_key(object_key)
    size_bytes = len(payload)
    with closing(session_factory()) as session:
        artifact = session.query(Artifact).filter(Artifact.object_key == object_key).first()
        if artifact is None:
            artifact = Artifact(
                object_key=object_key,
                created_at=created_at,
                size_bytes=size_bytes,
                mime_type=mime_type,
                checksum=checksum,
                artifact_type="raw",
                first_ingested_at=ingested_at,
                last_ingested_at=ingested_at,
                parent_object_key=None,
                parent_stage=None,
            )
            session.add(artifact)
        else:
            artifact.last_ingested_at = ingested_at
        session.commit()


def _ensure_timezone(value: datetime) -> datetime:
    """Ensure timestamps are timezone-aware and normalized to UTC."""
    if value.tzinfo is None:
        raise ValueError("capture_time must be timezone-aware")
    return value.astimezone(timezone.utc)


def _decode_payload(payload_b64: object | None) -> bytes | None:
    """Decode an optional base64 payload into raw bytes."""
    if payload_b64 is None:
        return None
    if not isinstance(payload_b64, str):
        raise ValueError("payload_b64 must be a base64 string")
    return base64.b64decode(payload_b64)


def _parse_datetime(value: object) -> datetime:
    """Parse an ISO 8601 datetime string into a timezone-aware datetime."""
    if not isinstance(value, str):
        raise ValueError("capture_time must be a string")
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    return _ensure_timezone(parsed)


def _optional_text(value: object | None) -> str | None:
    """Normalize optional text inputs to strings or None."""
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None
