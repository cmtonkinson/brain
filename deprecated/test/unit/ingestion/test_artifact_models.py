"""Unit tests for artifact and ingestion_artifact models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from models import Artifact, Ingestion, IngestionArtifact


def _create_ingestion(session_factory: sessionmaker) -> Ingestion:
    """Create and persist a base ingestion record for testing."""
    with session_factory() as session:
        ingestion = Ingestion(
            source_type="unit-test",
            source_uri=None,
            source_actor=None,
            created_at=datetime.now(timezone.utc),
            status="queued",
            last_error=None,
        )
        session.add(ingestion)
        session.commit()
        session.refresh(ingestion)
        return ingestion


def _create_artifact(session_factory: sessionmaker, object_key: str) -> Artifact:
    """Create and persist a raw artifact record for testing."""
    now = datetime.now(timezone.utc)
    with session_factory() as session:
        artifact = Artifact(
            object_key=object_key,
            created_at=now,
            size_bytes=4,
            mime_type="text/plain",
            checksum="deadbeef",
            artifact_type="raw",
            first_ingested_at=now,
            last_ingested_at=now,
            parent_object_key=None,
            parent_stage=None,
        )
        session.add(artifact)
        session.commit()
        session.refresh(artifact)
        return artifact


def test_ingestion_artifacts_reject_duplicate_stage_object(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Duplicate (ingestion_id, stage, object_key) rows should fail."""
    ingestion = _create_ingestion(sqlite_session_factory)
    artifact = _create_artifact(sqlite_session_factory, "b1:sha256:" + "0" * 64)

    with sqlite_session_factory() as session:
        first = IngestionArtifact(
            ingestion_id=ingestion.id,
            stage="store",
            object_key=artifact.object_key,
            created_at=datetime.now(timezone.utc),
            status="success",
            error=None,
        )
        session.add(first)
        session.commit()

    with sqlite_session_factory() as session:
        duplicate = IngestionArtifact(
            ingestion_id=ingestion.id,
            stage="store",
            object_key=artifact.object_key,
            created_at=datetime.now(timezone.utc),
            status="success",
            error=None,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()


def test_ingestion_artifacts_reject_invalid_stage(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Invalid stage values should violate constraints."""
    ingestion = _create_ingestion(sqlite_session_factory)
    artifact = _create_artifact(sqlite_session_factory, "b1:sha256:" + "1" * 64)

    with sqlite_session_factory() as session:
        record = IngestionArtifact(
            ingestion_id=ingestion.id,
            stage="invalid",
            object_key=artifact.object_key,
            created_at=datetime.now(timezone.utc),
            status="success",
            error=None,
        )
        session.add(record)
        with pytest.raises(IntegrityError):
            session.commit()
