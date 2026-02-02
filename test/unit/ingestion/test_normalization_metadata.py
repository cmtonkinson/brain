"""Tests for normalization metadata persistence and regeneration."""

from datetime import datetime, timezone
from uuid import UUID

from ingestion.stages.normalize import (
    Stage3NormalizationRunner,
    regenerate_normalized_artifacts,
)
from models import (
    Artifact,
    ExtractionMetadata,
    Ingestion,
    IngestionArtifact,
    NormalizationMetadata,
)
from services.object_store import ObjectStore


def _create_ingestion(session_factory, *, now: datetime) -> Ingestion:
    with session_factory() as session:
        ingestion = Ingestion(
            source_type="test",
            source_uri="test://regenerate",
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
        session.add(
            Artifact(
                object_key=object_key,
                created_at=created_at,
                size_bytes=0,
                mime_type=mime_type,
                checksum="feedface",
                artifact_type="extracted",
                first_ingested_at=created_at,
                last_ingested_at=created_at,
                parent_object_key="raw",
                parent_stage="store",
            )
        )
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
                confidence=0.9,
                page_count=1,
                tool_metadata={"method": method},
                created_at=created_at,
                updated_at=created_at,
            )
        )
        session.commit()


def _record_stage_extract(
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


def test_regenerate_normalized_artifacts_restores_outputs(tmp_path, sqlite_session_factory):
    now = datetime(2025, 1, 3, 0, 0, tzinfo=timezone.utc)
    store = ObjectStore(tmp_path)
    ingestion = _create_ingestion(sqlite_session_factory, now=now)

    extracted_key = store.write(b"regenerate")
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
    _record_stage_extract(
        sqlite_session_factory,
        ingestion.id,
        object_key=extracted_key,
        created_at=now,
    )

    runner = Stage3NormalizationRunner(
        session_factory=sqlite_session_factory,
        object_store=store,
    )
    initial = runner.run(ingestion.id, now=now)
    assert initial.normalized_artifacts == 1

    with sqlite_session_factory() as session:
        normalized_before = (
            session.query(Artifact).filter(Artifact.artifact_type == "normalized").all()
        )
        assert len(normalized_before) == 1
        first_key = normalized_before[0].object_key
    regen = regenerate_normalized_artifacts(
        ingestion.id,
        session_factory=sqlite_session_factory,
        object_store=store,
        now=now,
    )
    assert regen.failures == 0

    with sqlite_session_factory() as session:
        normalized_after = (
            session.query(Artifact).filter(Artifact.artifact_type == "normalized").all()
        )
        assert len(normalized_after) == 1
        assert normalized_after[0].object_key == first_key
        metadata = session.query(NormalizationMetadata).all()
        assert len(metadata) == 1
        stage_rows = (
            session.query(IngestionArtifact).filter(IngestionArtifact.stage == "normalize").all()
        )
        assert len(stage_rows) == 1
        assert stage_rows[0].status == "success"
