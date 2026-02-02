"""Unit tests for hook dispatch behavior."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import logging
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from ingestion.hook_dispatch import dispatch_stage_hooks
from ingestion.hooks import HookFilters, clear_hooks, register_hook
from models import Artifact, Ingestion, IngestionArtifact, ProvenanceRecord, ProvenanceSource


def _create_ingestion(session_factory: sessionmaker) -> Ingestion:
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        ingestion = Ingestion(
            source_type="test",
            source_uri="http://example",
            source_actor="tester",
            created_at=now,
            status="queued",
            last_error=None,
        )
        session.add(ingestion)
        session.commit()
        session.refresh(ingestion)
        return ingestion


def _persist_stage_artifact_with_provenance(
    session_factory: sessionmaker,
    ingestion_id: uuid.UUID,
    object_key: str,
    stage: str,
    mime_type: str,
    source_type: str,
) -> None:
    now = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        artifact = Artifact(
            object_key=object_key,
            created_at=now,
            size_bytes=512,
            mime_type=mime_type,
            checksum="abc123",
            artifact_type="extracted",
            first_ingested_at=now,
            last_ingested_at=now,
            parent_object_key=None,
            parent_stage=None,
        )
        session.add(artifact)
        record = ProvenanceRecord(object_key=object_key, created_at=now, updated_at=now)
        session.add(record)
        session.flush()
        session.add(
            ProvenanceSource(
                provenance_id=record.id,
                ingestion_id=ingestion_id,
                source_type=source_type,
                source_uri="http://example",
                source_actor="tester",
                captured_at=now,
            )
        )
        session.add(
            IngestionArtifact(
                ingestion_id=ingestion_id,
                stage=stage,
                object_key=object_key,
                created_at=now,
                status="success",
                error=None,
            )
        )
        session.commit()


def test_hook_dispatch_invokes_matching_hook(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Hooks that match filters are dispatched with the provenance records."""
    clear_hooks()
    ingestion = _create_ingestion(sqlite_session_factory)
    _persist_stage_artifact_with_provenance(
        sqlite_session_factory,
        ingestion_id=ingestion.id,
        object_key="extract-one",
        stage="extract",
        mime_type="text/plain",
        source_type="extractor:text",
    )

    invoked: list[tuple] = []

    def callback(ingestion_id, stage, records):
        invoked.append((ingestion_id, stage, tuple(records)))

    register_hook(
        "extract",
        callback,
        filters=HookFilters(mime_types={"text/plain"}, source_types={"extractor:text"}),
    )

    result = dispatch_stage_hooks(
        ingestion.id,
        "extract",
        session_factory=sqlite_session_factory,
    )

    assert result.hooks_dispatched == 1
    assert len(invoked) == 1
    _, stage, records = invoked[0]
    assert stage == "extract"
    assert len(records) == 1
    assert records[0].object_key == "extract-one"
    clear_hooks()


def test_hook_dispatch_logs_failure_without_blocking(
    sqlite_session_factory: sessionmaker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Exceptions raised by hooks are logged but do not propagate."""
    clear_hooks()
    ingestion = _create_ingestion(sqlite_session_factory)
    _persist_stage_artifact_with_provenance(
        sqlite_session_factory,
        ingestion_id=ingestion.id,
        object_key="extract-two",
        stage="extract",
        mime_type="text/plain",
        source_type="extractor:text",
    )

    def raising_hook(_ingestion_id, _stage, _records):
        raise RuntimeError("boom")

    register_hook("extract", raising_hook)

    caplog.set_level(logging.ERROR)
    result = dispatch_stage_hooks(
        ingestion.id,
        "extract",
        session_factory=sqlite_session_factory,
    )

    assert result.hooks_dispatched == 0
    assert any("Hook" in record.getMessage() for record in caplog.records)
    clear_hooks()


def test_hook_dispatch_with_no_artifacts_dispatches_empty_records(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Hooks without filters still run when the stage emitted no artifacts."""
    clear_hooks()
    ingestion = _create_ingestion(sqlite_session_factory)

    called: list[tuple] = []

    def callback(ingestion_id, stage, records):
        called.append((ingestion_id, stage, tuple(records)))

    register_hook("store", callback)

    result = dispatch_stage_hooks(
        ingestion.id,
        "store",
        session_factory=sqlite_session_factory,
    )

    assert result.hooks_dispatched == 1
    assert called[0][1] == "store"
    assert called[0][2] == ()
    clear_hooks()
