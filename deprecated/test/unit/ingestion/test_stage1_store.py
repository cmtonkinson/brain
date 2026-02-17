"""Unit tests for Stage 1 store runner."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from ingestion.stages.store import Stage1StoreRequest, run_stage1_store
from models import Artifact, Ingestion, IngestionArtifact, ProvenanceRecord, ProvenanceSource
from services.object_store import ObjectStore


def _create_ingestion(session_factory: sessionmaker) -> Ingestion:
    """Create and persist a base ingestion record for testing."""
    with session_factory() as session:
        ingestion = Ingestion(
            source_type="signal",
            source_uri="signal://msg/123",
            source_actor="user-1",
            created_at=datetime.now(timezone.utc),
            status="queued",
            last_error=None,
        )
        session.add(ingestion)
        session.commit()
        session.refresh(ingestion)
        return ingestion


def test_stage1_store_success_and_skip(
    sqlite_session_factory: sessionmaker,
    tmp_path,
) -> None:
    """Duplicate payloads should reuse artifacts and mark skipped."""
    store = ObjectStore(tmp_path)
    payload = b"hello"
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    ingestion_one = _create_ingestion(sqlite_session_factory)
    request_one = Stage1StoreRequest(
        ingestion_id=ingestion_one.id,
        payload=payload,
        existing_object_key=None,
        source_type="signal",
        source_uri="signal://msg/123",
        source_actor="user-1",
        capture_time=now,
        mime_type="text/plain",
    )

    result_one = run_stage1_store(
        request_one,
        session_factory=sqlite_session_factory,
        object_store=store,
        now=now,
    )
    assert result_one.status == "success"
    assert result_one.object_key is not None

    ingestion_two = _create_ingestion(sqlite_session_factory)
    request_two = Stage1StoreRequest(
        ingestion_id=ingestion_two.id,
        payload=payload,
        existing_object_key=None,
        source_type="signal",
        source_uri="signal://msg/456",
        source_actor="user-2",
        capture_time=now,
        mime_type="text/plain",
    )

    result_two = run_stage1_store(
        request_two,
        session_factory=sqlite_session_factory,
        object_store=store,
        now=now,
    )
    assert result_two.status == "skipped"
    assert result_two.object_key == result_one.object_key

    with sqlite_session_factory() as session:
        artifacts = session.query(Artifact).all()
        assert len(artifacts) == 1
        stage_rows = (
            session.query(IngestionArtifact).filter(IngestionArtifact.stage == "store").all()
        )
        assert len(stage_rows) == 2
        provenance_records = session.query(ProvenanceRecord).all()
        provenance_sources = session.query(ProvenanceSource).all()
        assert len(provenance_records) == 1
        assert len(provenance_sources) == 2


def test_stage1_store_existing_object_key_success(
    sqlite_session_factory: sessionmaker,
    tmp_path,
) -> None:
    """Existing object keys should be recorded without rewriting blobs."""
    store = ObjectStore(tmp_path)
    payload = b"existing"
    object_key = store.write(payload)
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    ingestion = _create_ingestion(sqlite_session_factory)
    request = Stage1StoreRequest(
        ingestion_id=ingestion.id,
        payload=None,
        existing_object_key=object_key,
        source_type="signal",
        source_uri="signal://msg/789",
        source_actor="user-3",
        capture_time=now,
        mime_type="text/plain",
    )

    result = run_stage1_store(
        request,
        session_factory=sqlite_session_factory,
        object_store=store,
        now=now,
    )

    assert result.status == "success"
    assert result.object_key == object_key


def test_stage1_store_missing_existing_key_fails(
    sqlite_session_factory: sessionmaker,
    tmp_path,
) -> None:
    """Missing existing_object_key should record failure."""
    store = ObjectStore(tmp_path)
    payload = b"missing"
    object_key = store.write(payload)
    store.delete(object_key)
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    ingestion = _create_ingestion(sqlite_session_factory)
    request = Stage1StoreRequest(
        ingestion_id=ingestion.id,
        payload=None,
        existing_object_key=object_key,
        source_type="signal",
        source_uri="signal://msg/000",
        source_actor="user-4",
        capture_time=now,
        mime_type="text/plain",
    )

    result = run_stage1_store(
        request,
        session_factory=sqlite_session_factory,
        object_store=store,
        now=now,
    )

    assert result.status == "failed"
    assert result.object_key is None
    assert result.error
