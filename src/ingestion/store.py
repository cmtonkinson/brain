"""Persistence helpers for Tier 0 raw artifact storage."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from config import settings
from models import Artifact
from services.database import get_sync_session
from services.object_store import ObjectStore

_OBJECT_KEY_PREFIX = "b1:sha256:"


@dataclass(frozen=True)
class RawArtifactResult:
    """Metadata describing a stored raw artifact."""

    object_key: str
    checksum: str
    size_bytes: int
    mime_type: str | None
    created: bool


def store_raw_artifact(
    payload: bytes | bytearray | memoryview | str,
    *,
    mime_type: str | None,
    ingested_at: datetime,
    session_factory: Callable[[], Session] | None = None,
    object_store: ObjectStore | None = None,
) -> RawArtifactResult:
    """Write raw payload bytes and persist artifact metadata."""
    if ingested_at.tzinfo is None:
        raise ValueError("ingested_at must be timezone-aware")

    normalized = _normalize_payload(payload)
    store = object_store or ObjectStore(settings.objects.root_dir)
    object_key = store.write(normalized)
    checksum = _checksum_from_object_key(object_key)
    size_bytes = len(normalized)
    session_factory = session_factory or get_sync_session

    with closing(session_factory()) as session:
        artifact = session.query(Artifact).filter(Artifact.object_key == object_key).first()
        if artifact is not None:
            artifact.last_ingested_at = ingested_at
            session.commit()
            return RawArtifactResult(
                object_key=object_key,
                checksum=checksum,
                size_bytes=size_bytes,
                mime_type=artifact.mime_type,
                created=False,
            )

        created_at = datetime.now(timezone.utc)
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
        session.commit()
        return RawArtifactResult(
            object_key=object_key,
            checksum=checksum,
            size_bytes=size_bytes,
            mime_type=mime_type,
            created=True,
        )


def read_raw_artifact(
    object_key: str,
    *,
    object_store: ObjectStore | None = None,
) -> bytes:
    """Read raw artifact bytes by object key."""
    store = object_store or ObjectStore(settings.objects.root_dir)
    return store.read(object_key)


def _normalize_payload(payload: bytes | bytearray | memoryview | str) -> bytes:
    """Normalize supported payload types into raw bytes."""
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, (bytearray, memoryview)):
        return bytes(payload)
    if isinstance(payload, str):
        return payload.encode("utf-8")
    raise TypeError("payload must be bytes-like or UTF-8 text")


def _checksum_from_object_key(object_key: str) -> str:
    """Extract the checksum digest from a content-addressed object key."""
    if not object_key.startswith(_OBJECT_KEY_PREFIX):
        raise ValueError("object_key must start with 'b1:sha256:'")
    digest = object_key[len(_OBJECT_KEY_PREFIX) :]
    if len(digest) != 64:
        raise ValueError("object_key digest must be 64 hex characters")
    return digest
