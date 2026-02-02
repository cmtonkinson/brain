"""Tests for Stage 2 extraction runner."""

from datetime import datetime, timezone

from ingestion.extractors import ExtractedArtifact, ExtractorContext, ExtractorRegistry
from ingestion.extractors.text import TextExtractor
from ingestion.stages.extract import Stage2ExtractionRunner
from models import (
    Artifact,
    ExtractionMetadata,
    Ingestion,
    IngestionArtifact,
    ProvenanceRecord,
    ProvenanceSource,
)
from services.object_store import ObjectStore


def _create_ingestion(session_factory, *, now) -> Ingestion:
    with session_factory() as session:
        ingestion = Ingestion(
            source_type="test",
            source_uri="test://source",
            source_actor="actor",
            created_at=now,
            status="queued",
            last_error=None,
        )
        session.add(ingestion)
        session.commit()
        session.refresh(ingestion)
        return ingestion


def _insert_raw_artifact(session_factory, object_key, *, mime_type, created_at):
    with session_factory() as session:
        artifact = Artifact(
            object_key=object_key,
            created_at=created_at,
            size_bytes=0,
            mime_type=mime_type,
            checksum="deadbeef",
            artifact_type="raw",
            first_ingested_at=created_at,
            last_ingested_at=created_at,
            parent_object_key=None,
            parent_stage=None,
        )
        session.add(artifact)
        session.commit()


class _FailingExtractor(TextExtractor):
    def can_extract(self, context: ExtractorContext) -> bool:
        return context.mime_type == "image/png"

    def extract(self, context: ExtractorContext) -> list[ExtractedArtifact]:
        raise RuntimeError("boom")


def test_stage2_extraction_fan_out(tmp_path, sqlite_session_factory):
    """Successful Stage 2 extraction emits metadata and provenance per artifact."""
    now = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    store = ObjectStore(tmp_path)
    payloads = [b"alpha", b"beta"]

    ingestion = _create_ingestion(sqlite_session_factory, now=now)
    for payload in payloads:
        object_key = store.write(payload)
        _insert_raw_artifact(
            sqlite_session_factory,
            object_key,
            mime_type="text/plain",
            created_at=now,
        )
        with sqlite_session_factory() as session:
            session.add(
                IngestionArtifact(
                    ingestion_id=ingestion.id,
                    stage="store",
                    object_key=object_key,
                    created_at=now,
                    status="success",
                    error=None,
                )
            )
            session.commit()

    runner = Stage2ExtractionRunner(
        session_factory=sqlite_session_factory,
        object_store=store,
    )
    result = runner.run(ingestion.id, now=now)

    assert result.extracted_artifacts == 2
    assert result.failures == 0
    assert not result.errors

    with sqlite_session_factory() as session:
        extracted = session.query(Artifact).filter(Artifact.artifact_type == "extracted").all()
        assert len(extracted) == 2
        metadata = session.query(ExtractionMetadata).all()
        assert len(metadata) == 2
        objects = {md.object_key for md in metadata}
        assert objects == {art.object_key for art in extracted}
        stage_rows = (
            session.query(IngestionArtifact).filter(IngestionArtifact.stage == "extract").all()
        )
        assert len(stage_rows) == 2
        assert all(row.status == "success" for row in stage_rows)
        provenance = session.query(ProvenanceRecord).all()
        assert len(provenance) == 2
        sources = session.query(ProvenanceSource).all()
        assert len(sources) == 2


def test_stage2_extraction_partial_failure(tmp_path, sqlite_session_factory):
    """Failures for one artifact do not block others."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    store = ObjectStore(tmp_path)

    ingestion = _create_ingestion(sqlite_session_factory, now=now)
    object_key_success = store.write(b"ok")
    _insert_raw_artifact(
        sqlite_session_factory,
        object_key_success,
        mime_type="text/plain",
        created_at=now,
    )
    object_key_failure = store.write(b"fail")
    _insert_raw_artifact(
        sqlite_session_factory,
        object_key_failure,
        mime_type="image/png",
        created_at=now,
    )
    with sqlite_session_factory() as session:
        session.add_all(
            [
                IngestionArtifact(
                    ingestion_id=ingestion.id,
                    stage="store",
                    object_key=object_key_success,
                    created_at=now,
                    status="success",
                    error=None,
                ),
                IngestionArtifact(
                    ingestion_id=ingestion.id,
                    stage="store",
                    object_key=object_key_failure,
                    created_at=now,
                    status="success",
                    error=None,
                ),
            ]
        )
        session.commit()

    registry = ExtractorRegistry([TextExtractor(), _FailingExtractor()])
    runner = Stage2ExtractionRunner(
        session_factory=sqlite_session_factory,
        object_store=store,
        registry=registry,
    )
    result = runner.run(ingestion.id, now=now)

    assert result.extracted_artifacts == 1
    assert result.failures == 1
    assert len(result.errors) == 1
    assert "boom" in result.errors[0]

    with sqlite_session_factory() as session:
        extracted = session.query(Artifact).filter(Artifact.artifact_type == "extracted").all()
        assert len(extracted) == 1
        failure_rows = (
            session.query(IngestionArtifact).filter(IngestionArtifact.stage == "extract").all()
        )
        assert len(failure_rows) == 2
        assert any(row.status == "failed" for row in failure_rows)
        assert any(row.status == "success" for row in failure_rows)
        metadata = session.query(ExtractionMetadata).all()
        assert len(metadata) == 1
        provenance = session.query(ProvenanceRecord).all()
        assert len(provenance) == 1

        # Verify that the stage run is marked as failed due to per-artifact failures
        from models import IngestionStageRun

        stage_run = (
            session.query(IngestionStageRun)
            .filter(
                IngestionStageRun.ingestion_id == ingestion.id,
                IngestionStageRun.stage == "extract",
            )
            .order_by(IngestionStageRun.created_at.desc())
            .first()
        )
        assert stage_run is not None
        assert stage_run.status == "failed"
        assert "artifact(s) failed extraction" in stage_run.error
        assert stage_run.started_at is not None
        assert stage_run.finished_at is not None
        assert stage_run.finished_at >= stage_run.started_at
