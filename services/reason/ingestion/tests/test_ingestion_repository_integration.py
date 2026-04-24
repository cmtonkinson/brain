"""Real-provider integration tests for Ingestion Service Postgres repository."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.reason.ingestion.data.repository import (
    PostgresIngestionRepository,
)
from services.reason.ingestion.data.runtime import (
    IngestionPostgresRuntime,
)
from services.reason.ingestion.domain import (
    IngestionStatus,
)
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)

pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def _repo(settings) -> PostgresIngestionRepository:
    runtime = IngestionPostgresRuntime.from_settings(settings)
    return PostgresIngestionRepository(runtime.schema_sessions)


def test_ingestion_create_and_stage_roundtrip(
    migrated_integration_settings,
) -> None:
    """Repository should persist ingestion and stage run records."""
    repo = _repo(migrated_integration_settings)
    now = datetime.now(UTC)

    ingestion = repo.create_ingestion(
        status="queued",
        source_type="file",
        source_uri="file:///tmp/test.pdf",
        source_actor="operator",
        capture_time=now,
        mime_type="application/pdf",
        created_at=now,
    )
    assert ingestion.id
    assert ingestion.status == IngestionStatus.queued

    fetched = repo.get_ingestion(ingestion_id=ingestion.id)
    assert fetched is not None
    assert fetched.source_uri == "file:///tmp/test.pdf"

    stage_run = repo.create_stage_run(
        ingestion_id=ingestion.id,
        stage="store",
        status="running",
        started_at=now,
        created_at=now,
    )
    assert stage_run.id

    repo.finish_stage_run(
        stage_run_id=stage_run.id,
        status="success",
        error=None,
        finished_at=now,
    )

    runs = repo.list_stage_runs(
        ingestion_id=ingestion.id,
        stage="store",
    )
    assert len(runs) == 1
    assert runs[0].status.value == "success"


def test_artifact_outcome_and_provenance(
    migrated_integration_settings,
) -> None:
    """Repository should persist artifact outcomes and provenance."""
    repo = _repo(migrated_integration_settings)
    now = datetime.now(UTC)

    ingestion = repo.create_ingestion(
        status="queued",
        source_type="file",
        source_uri="file:///tmp/test2.pdf",
        source_actor="operator",
        capture_time=now,
        mime_type="application/pdf",
        created_at=now,
    )

    repo.create_stage_artifact_outcome(
        ingestion_id=ingestion.id,
        stage="store",
        object_key="objects/ab/cd/abcd" + "ef" * 28 + ".blob",
        parent_object_key=None,
        status="success",
        error=None,
        created_at=now,
    )

    outcomes = repo.list_stage_artifact_outcomes(
        ingestion_id=ingestion.id,
        stage="store",
        status=None,
    )
    assert len(outcomes) == 1
    assert outcomes[0].status.value == "success"

    provenance = repo.get_or_create_provenance(
        object_key="objects/ab/cd/abcd" + "ef" * 28 + ".blob",
        created_at=now,
    )
    assert provenance.id

    source = repo.upsert_provenance_source(
        provenance_id=provenance.id,
        ingestion_id=ingestion.id,
        source_type="file",
        source_uri="file:///tmp/test2.pdf",
        source_actor="operator",
        captured_at=now,
    )
    assert source is not None
    assert source.provenance_id == provenance.id


def test_ingestion_status_update(
    migrated_integration_settings,
) -> None:
    """Repository should update ingestion status and error."""
    repo = _repo(migrated_integration_settings)
    now = datetime.now(UTC)

    ingestion = repo.create_ingestion(
        status="queued",
        source_type="url",
        source_uri="https://example.com/doc.pdf",
        source_actor="agent",
        capture_time=now,
        mime_type="application/pdf",
        created_at=now,
    )

    repo.update_ingestion_status(
        ingestion_id=ingestion.id,
        status="complete",
        last_error=None,
        updated_at=now,
    )

    fetched = repo.get_ingestion(ingestion_id=ingestion.id)
    assert fetched is not None
    assert fetched.status == IngestionStatus.complete
