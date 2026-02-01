"""Unit tests for provenance models and constraints."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from models import Artifact, Ingestion, ProvenanceRecord, ProvenanceSource


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
            mime_type=None,
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


def test_provenance_sources_dedupe_constraint(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Duplicate provenance sources should be rejected by the database."""
    ingestion = _create_ingestion(sqlite_session_factory)
    artifact = _create_artifact(sqlite_session_factory, "b1:sha256:" + "2" * 64)

    with sqlite_session_factory() as session:
        record = ProvenanceRecord(
            object_key=artifact.object_key,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(record)
        session.commit()
        session.refresh(record)

    with sqlite_session_factory() as session:
        first = ProvenanceSource(
            provenance_id=record.id,
            ingestion_id=ingestion.id,
            source_type="email",
            source_uri="mail://example",
            source_actor="user-1",
            captured_at=datetime.now(timezone.utc),
        )
        session.add(first)
        session.commit()

    with sqlite_session_factory() as session:
        duplicate = ProvenanceSource(
            provenance_id=record.id,
            ingestion_id=ingestion.id,
            source_type="email",
            source_uri="mail://example",
            source_actor="user-1",
            captured_at=datetime.now(timezone.utc),
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()


def test_provenance_sources_allow_null_fields(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Null source_uri and source_actor should persist successfully."""
    ingestion = _create_ingestion(sqlite_session_factory)
    artifact = _create_artifact(sqlite_session_factory, "b1:sha256:" + "3" * 64)

    with sqlite_session_factory() as session:
        record = ProvenanceRecord(
            object_key=artifact.object_key,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(record)
        session.commit()
        session.refresh(record)

    with sqlite_session_factory() as session:
        source = ProvenanceSource(
            provenance_id=record.id,
            ingestion_id=ingestion.id,
            source_type="file",
            source_uri=None,
            source_actor=None,
            captured_at=datetime.now(timezone.utc),
        )
        session.add(source)
        session.commit()
        session.refresh(source)
        assert source.source_uri is None
        assert source.source_actor is None
