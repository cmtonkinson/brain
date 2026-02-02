"""Unit tests for Stage 3 normalization runner."""

from datetime import datetime, timezone
from uuid import UUID

from ingestion.normalizers import NormalizerRegistry
from ingestion.normalizers.text import DefaultTextNormalizer
from ingestion.stages.normalize import Stage3NormalizationRunner
from models import (
    Artifact,
    ExtractionMetadata,
    Ingestion,
    IngestionArtifact,
    NormalizationMetadata,
    ProvenanceRecord,
    ProvenanceSource,
)
from services.object_store import ObjectStore


def _create_ingestion(session_factory, *, now: datetime) -> Ingestion:
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


def _insert_extracted_artifact(
    session_factory,
    object_key: str,
    *,
    mime_type: str,
    created_at: datetime,
) -> None:
    with session_factory() as session:
        artifact = Artifact(
            object_key=object_key,
            created_at=created_at,
            size_bytes=0,
            mime_type=mime_type,
            checksum="deadbeef",
            artifact_type="extracted",
            first_ingested_at=created_at,
            last_ingested_at=created_at,
            parent_object_key="raw",
            parent_stage="store",
        )
        session.add(artifact)
        session.commit()


def _record_extraction_metadata(
    session_factory,
    object_key: str,
    *,
    method: str,
    created_at: datetime,
) -> None:
    with session_factory() as session:
        session.add(
            ExtractionMetadata(
                object_key=object_key,
                method=method,
                confidence=0.5,
                page_count=1,
                tool_metadata={"method": method},
                created_at=created_at,
                updated_at=created_at,
            )
        )
        session.commit()


def _record_extraction_ingestion_artifact(
    session_factory,
    ingestion_id: UUID,
    *,
    object_key: str,
    created_at: datetime,
) -> None:
    with session_factory() as session:
        session.add(
            IngestionArtifact(
                ingestion_id=ingestion_id,
                stage="extract",
                object_key=object_key,
                created_at=created_at,
                status="success",
                error=None,
            )
        )
        session.commit()


def test_stage3_normalization_creates_normalized_artifact(tmp_path, sqlite_session_factory):
    now = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    store = ObjectStore(tmp_path)
    ingestion = _create_ingestion(sqlite_session_factory, now=now)

    payload = b"alpha\n\nadvertisement line\n\nbeta\n"
    extracted_key = store.write(payload)
    _insert_extracted_artifact(
        sqlite_session_factory,
        extracted_key,
        mime_type="text/plain",
        created_at=now,
    )
    _record_extraction_metadata(
        sqlite_session_factory,
        extracted_key,
        method="text/plain",
        created_at=now,
    )
    _record_extraction_ingestion_artifact(
        sqlite_session_factory,
        ingestion.id,
        object_key=extracted_key,
        created_at=now,
    )

    runner = Stage3NormalizationRunner(
        session_factory=sqlite_session_factory,
        object_store=store,
    )
    result = runner.run(ingestion.id, now=now)

    assert result.normalized_artifacts == 1
    assert result.failures == 0
    assert result.errors == ()

    with sqlite_session_factory() as session:
        normalized = session.query(Artifact).filter(Artifact.artifact_type == "normalized").all()
        assert len(normalized) == 1
        record = normalized[0]
        assert record.parent_stage == "extract"
        assert record.parent_object_key == extracted_key

        metadata = session.query(NormalizationMetadata).all()
        assert len(metadata) == 1
        assert metadata[0].object_key == record.object_key

        provenance_records = session.query(ProvenanceRecord).all()
        assert len(provenance_records) == 1
        sources = session.query(ProvenanceSource).all()
        assert len(sources) == 1

        stage_rows = (
            session.query(IngestionArtifact).filter(IngestionArtifact.stage == "normalize").all()
        )
        assert len(stage_rows) == 1
        assert stage_rows[0].status == "success"

    normalized_text = store.read(record.object_key).decode("utf-8")
    assert "advertisement" not in normalized_text
    assert normalized_text == "alpha\n\nbeta"


class _FailingNormalizer(DefaultTextNormalizer):
    def can_normalize(self, context):  # type: ignore[override]
        return context.mime_type == "text/fail"

    def normalize(self, context):  # type: ignore[override]
        raise RuntimeError("boom")


def test_stage3_normalization_partial_failure_records_failure(tmp_path, sqlite_session_factory):
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    store = ObjectStore(tmp_path)
    ingestion = _create_ingestion(sqlite_session_factory, now=now)

    success_key = store.write(b"ok")
    failure_key = store.write(b"fail")

    _insert_extracted_artifact(
        sqlite_session_factory,
        success_key,
        mime_type="text/plain",
        created_at=now,
    )
    _insert_extracted_artifact(
        sqlite_session_factory,
        failure_key,
        mime_type="text/fail",
        created_at=now,
    )
    for key in (success_key, failure_key):
        _record_extraction_metadata(
            sqlite_session_factory,
            key,
            method="text/plain",
            created_at=now,
        )
        _record_extraction_ingestion_artifact(
            sqlite_session_factory,
            ingestion.id,
            object_key=key,
            created_at=now,
        )

    runner = Stage3NormalizationRunner(
        session_factory=sqlite_session_factory,
        object_store=store,
        registry=NormalizerRegistry([_FailingNormalizer(), DefaultTextNormalizer()]),
    )
    result = runner.run(ingestion.id, now=now)

    assert result.normalized_artifacts == 1
    assert result.failures == 1
    assert len(result.errors) == 1
    assert "FailingNormalizer" in result.errors[0]

    with sqlite_session_factory() as session:
        normalized = session.query(Artifact).filter(Artifact.artifact_type == "normalized").all()
        assert len(normalized) == 1
        stage_rows = (
            session.query(IngestionArtifact).filter(IngestionArtifact.stage == "normalize").all()
        )
        assert len(stage_rows) == 2
        assert any(row.status == "failed" for row in stage_rows)
        assert any(row.status == "success" for row in stage_rows)
