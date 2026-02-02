"""Unit tests for embeddings dispatch traceability."""

from datetime import datetime, timezone

from ingestion.index_handoff import dispatch_embeddings_for_ingestion
from models import (
    Artifact,
    Ingestion,
    IngestionArtifact,
    IngestionEmbeddingDispatch,
)


def _create_ingestion(session_factory, *, now: datetime) -> Ingestion:
    with session_factory() as session:
        ingestion = Ingestion(
            source_type="test",
            source_uri="test://example",
            source_actor="author",
            created_at=now,
            status="queued",
            last_error=None,
        )
        session.add(ingestion)
        session.commit()
        session.refresh(ingestion)
        return ingestion


def _insert_artifact(
    session_factory,
    object_key: str,
    *,
    created_at: datetime,
) -> None:
    with session_factory() as session:
        session.add(
            Artifact(
                object_key=object_key,
                created_at=created_at,
                size_bytes=0,
                mime_type="text/markdown",
                checksum="deadbeef",
                artifact_type="normalized",
                first_ingested_at=created_at,
                last_ingested_at=created_at,
                parent_object_key=None,
                parent_stage="extract",
            )
        )
        session.commit()


def _insert_ingestion_artifact(
    session_factory,
    ingestion_id,
    *,
    object_key: str,
    created_at: datetime,
) -> None:
    with session_factory() as session:
        session.add(
            IngestionArtifact(
                ingestion_id=ingestion_id,
                stage="normalize",
                object_key=object_key,
                created_at=created_at,
                status="success",
                error=None,
            )
        )
        session.commit()


def test_dispatch_embeddings_records_success(sqlite_session_factory):
    """Successful dispatch stores per-artifact records."""
    now = datetime(2026, 2, 2, 1, 0, tzinfo=timezone.utc)
    ingestion = _create_ingestion(sqlite_session_factory, now=now)
    keys = ["normalized-a", "normalized-b"]
    for key in keys:
        _insert_artifact(sqlite_session_factory, key, created_at=now)
        _insert_ingestion_artifact(
            sqlite_session_factory, ingestion.id, object_key=key, created_at=now
        )

    seen: list[str] = []

    def recording_dispatcher(_ingestion_id, object_key):
        seen.append(object_key)

    outcomes = dispatch_embeddings_for_ingestion(
        ingestion.id,
        dispatcher=recording_dispatcher,
        session_factory=sqlite_session_factory,
        now=now,
    )

    assert len(outcomes) == 2
    assert set(outcome.normalized_object_key for outcome in outcomes) == set(keys)
    assert all(outcome.status == "success" for outcome in outcomes)
    assert set(seen) == set(keys)
    with sqlite_session_factory() as session:
        rows = session.query(IngestionEmbeddingDispatch).filter_by(ingestion_id=ingestion.id).all()
    assert len(rows) == 2
    assert all(row.status == "success" for row in rows)


def test_dispatch_embeddings_partial_failure(sqlite_session_factory):
    """Failures for one artifact do not affect others."""
    now = datetime(2026, 2, 2, 2, 0, tzinfo=timezone.utc)
    ingestion = _create_ingestion(sqlite_session_factory, now=now)
    keys = ["normalized-a", "normalized-b"]
    for key in keys:
        _insert_artifact(sqlite_session_factory, key, created_at=now)
        _insert_ingestion_artifact(
            sqlite_session_factory, ingestion.id, object_key=key, created_at=now
        )

    def fail_on_first(_ingestion_id, object_key):
        if object_key == keys[0]:
            raise ValueError("boom")

    outcomes = dispatch_embeddings_for_ingestion(
        ingestion.id,
        dispatcher=fail_on_first,
        session_factory=sqlite_session_factory,
        now=now,
    )

    assert len(outcomes) == 2
    status_by_key = {outcome.normalized_object_key: outcome.status for outcome in outcomes}
    assert status_by_key[keys[0]] == "failed"
    assert status_by_key[keys[1]] == "success"
    errors = {outcome.normalized_object_key: outcome.error for outcome in outcomes}
    assert errors[keys[0]] == "boom"
    with sqlite_session_factory() as session:
        rows = session.query(IngestionEmbeddingDispatch).filter_by(ingestion_id=ingestion.id).all()
    assert len(rows) == 2
    failed = [row for row in rows if row.status == "failed"]
    succeeded = [row for row in rows if row.status == "success"]
    assert len(failed) == 1
    assert len(succeeded) == 1


def test_dispatch_embeddings_skips_when_no_artifacts(sqlite_session_factory):
    """No artifacts produces no dispatch attempts."""
    now = datetime(2026, 2, 2, 3, 0, tzinfo=timezone.utc)
    ingestion = _create_ingestion(sqlite_session_factory, now=now)

    outcomes = dispatch_embeddings_for_ingestion(
        ingestion.id,
        session_factory=sqlite_session_factory,
        now=now,
    )

    assert outcomes == ()
    with sqlite_session_factory() as session:
        count = (
            session.query(IngestionEmbeddingDispatch).filter_by(ingestion_id=ingestion.id).count()
        )
    assert count == 0
