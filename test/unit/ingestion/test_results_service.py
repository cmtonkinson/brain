"""Unit tests for the ingestion results service."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from ingestion.errors import IngestionNotFound
from ingestion.results import get_ingestion_results
from models import Artifact, Ingestion, IngestionArtifact


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


def _persist_artifact(
    session_factory: sessionmaker,
    object_key: str,
    stage: str,
    size_bytes: int,
    mime_type: str,
    artifact_type: str,
    ingestion_id: uuid.UUID,
) -> None:
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        artifact = Artifact(
            object_key=object_key,
            created_at=now,
            size_bytes=size_bytes,
            mime_type=mime_type,
            checksum="abc123",
            artifact_type=artifact_type,
            first_ingested_at=now,
            last_ingested_at=now,
            parent_object_key=None,
            parent_stage=None,
        )
        session.add(artifact)
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


def test_get_ingestion_results_returns_grouped_outcomes(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Service returns stage outcomes grouped deterministically."""
    ingestion = _create_ingestion(sqlite_session_factory)
    _persist_artifact(
        sqlite_session_factory,
        object_key="raw-one",
        stage="store",
        size_bytes=128,
        mime_type="image/png",
        artifact_type="raw",
        ingestion_id=ingestion.id,
    )
    _persist_artifact(
        sqlite_session_factory,
        object_key="normalized-one",
        stage="extract",
        size_bytes=256,
        mime_type="text/plain",
        artifact_type="extracted",
        ingestion_id=ingestion.id,
    )

    results = get_ingestion_results(ingestion.id, session_factory=sqlite_session_factory)

    assert results.ingestion_id == ingestion.id
    store_stage = results.stages[0]
    assert store_stage.stage == "store"
    assert len(store_stage.outcomes) == 1
    assert store_stage.outcomes[0].mime_type == "image/png"

    extract_stage = results.stages[1]
    assert extract_stage.stage == "extract"
    assert len(extract_stage.outcomes) == 1
    assert extract_stage.outcomes[0].mime_type == "text/plain"

    normalize_stage = results.stages[2]
    assert normalize_stage.stage == "normalize"
    assert normalize_stage.outcomes == ()
    anchor_stage = results.stages[3]
    assert anchor_stage.stage == "anchor"
    assert anchor_stage.outcomes == ()


def test_get_ingestion_results_returns_empty_for_unrun_stages(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Stages without outcomes return empty outcome lists."""
    ingestion = _create_ingestion(sqlite_session_factory)

    results = get_ingestion_results(ingestion.id, session_factory=sqlite_session_factory)

    assert results.stages[0].stage == "store"
    for stage in results.stages:
        assert stage.outcomes == ()


def test_get_ingestion_results_unknown_ingestion_raises(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Unknown ingestion identifiers raise IngestionNotFound."""
    with pytest.raises(IngestionNotFound):
        get_ingestion_results(uuid.uuid4(), session_factory=sqlite_session_factory)
