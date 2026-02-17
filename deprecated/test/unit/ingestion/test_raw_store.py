"""Unit tests for raw artifact storage helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from ingestion.store import read_raw_artifact, store_raw_artifact
from models import Artifact
from services.object_store import ObjectStore


def test_store_and_read_raw_artifact(
    sqlite_session_factory: sessionmaker,
    tmp_path,
) -> None:
    """Stored payloads should be retrievable byte-for-byte."""
    store = ObjectStore(tmp_path)
    payload = b"hello"
    ingested_at = datetime.now(timezone.utc)

    result = store_raw_artifact(
        payload,
        mime_type="text/plain",
        ingested_at=ingested_at,
        session_factory=sqlite_session_factory,
        object_store=store,
    )

    assert result.object_key.startswith("b1:sha256:")
    assert result.size_bytes == len(payload)
    assert result.mime_type == "text/plain"
    assert result.created is True

    with sqlite_session_factory() as session:
        artifact = session.query(Artifact).filter(Artifact.object_key == result.object_key).first()
        assert artifact is not None
        assert artifact.checksum == result.checksum
        assert artifact.first_ingested_at == ingested_at.replace(tzinfo=None)
        assert artifact.last_ingested_at == ingested_at.replace(tzinfo=None)

    loaded = read_raw_artifact(result.object_key, object_store=store)
    assert loaded == payload


def test_store_raw_artifact_allows_null_mime_type(
    sqlite_session_factory: sessionmaker,
    tmp_path,
) -> None:
    """Missing mime_type should persist as null."""
    store = ObjectStore(tmp_path)
    payload = b"payload"
    ingested_at = datetime.now(timezone.utc)

    result = store_raw_artifact(
        payload,
        mime_type=None,
        ingested_at=ingested_at,
        session_factory=sqlite_session_factory,
        object_store=store,
    )

    with sqlite_session_factory() as session:
        artifact = session.query(Artifact).filter(Artifact.object_key == result.object_key).first()
        assert artifact is not None
        assert artifact.mime_type is None
