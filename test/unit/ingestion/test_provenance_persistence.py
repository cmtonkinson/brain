"""Unit tests for provenance persistence helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from ingestion.provenance import ProvenanceSourceInput, record_provenance
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


def test_record_provenance_dedupes_sources(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Duplicate sources should not create multiple rows."""
    ingestion = _create_ingestion(sqlite_session_factory)
    artifact = _create_artifact(sqlite_session_factory, "b1:sha256:" + "4" * 64)
    captured_at = datetime.now(timezone.utc)
    source = ProvenanceSourceInput(
        source_type="email",
        source_uri=None,
        source_actor=None,
        captured_at=captured_at,
    )

    with sqlite_session_factory() as session:
        record_provenance(
            session,
            object_key=artifact.object_key,
            ingestion_id=ingestion.id,
            sources=[source],
            now=captured_at,
        )
        session.commit()

    with sqlite_session_factory() as session:
        record_provenance(
            session,
            object_key=artifact.object_key,
            ingestion_id=ingestion.id,
            sources=[source],
            now=captured_at,
        )
        session.commit()
        record = (
            session.query(ProvenanceRecord)
            .filter(ProvenanceRecord.object_key == artifact.object_key)
            .first()
        )
        count = (
            session.query(ProvenanceSource)
            .filter(ProvenanceSource.provenance_id == record.id)
            .count()
        )
        assert count == 1


def test_record_provenance_updates_timestamp(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Adding sources should update provenance_records.updated_at."""
    ingestion = _create_ingestion(sqlite_session_factory)
    artifact = _create_artifact(sqlite_session_factory, "b1:sha256:" + "5" * 64)
    captured_at = datetime.now(timezone.utc)
    source = ProvenanceSourceInput(
        source_type="file",
        source_uri="file://example.txt",
        source_actor=None,
        captured_at=captured_at,
    )

    with sqlite_session_factory() as session:
        record = record_provenance(
            session,
            object_key=artifact.object_key,
            ingestion_id=ingestion.id,
            sources=[source],
            now=captured_at,
        )
        session.commit()
        original_updated = record.updated_at

    later = captured_at + timedelta(minutes=5)
    with sqlite_session_factory() as session:
        record = record_provenance(
            session,
            object_key=artifact.object_key,
            ingestion_id=ingestion.id,
            sources=[source],
            now=later,
        )
        session.commit()
        assert record.updated_at == later.replace(tzinfo=None)
        assert record.updated_at != original_updated


def test_record_provenance_allows_null_source_fields(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Null source_uri and source_actor should persist."""
    ingestion = _create_ingestion(sqlite_session_factory)
    artifact = _create_artifact(sqlite_session_factory, "b1:sha256:" + "6" * 64)
    captured_at = datetime.now(timezone.utc)
    source = ProvenanceSourceInput(
        source_type="web",
        source_uri=None,
        source_actor=None,
        captured_at=captured_at,
    )

    with sqlite_session_factory() as session:
        record_provenance(
            session,
            object_key=artifact.object_key,
            ingestion_id=ingestion.id,
            sources=[source],
            now=captured_at,
        )
        session.commit()
        stored = session.query(ProvenanceSource).first()
        assert stored is not None
        assert stored.source_uri is None
        assert stored.source_actor is None
