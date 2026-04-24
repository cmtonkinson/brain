"""Real-provider integration tests for Job Service Postgres repository."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.reason.job.data.repository import PostgresJobRepository
from services.reason.job.data.runtime import JobPostgresRuntime
from services.reason.job.domain import (
    JobIntent,
    JobRecord,
)
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)

pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def _repo(settings) -> PostgresJobRepository:
    runtime = JobPostgresRuntime.from_settings(settings)
    return PostgresJobRepository(runtime.schema_sessions)


def _create_intent(repo: PostgresJobRepository) -> JobIntent:
    now = datetime.now(UTC)
    return repo.create_job_intent(
        summary="Integration test intent",
        action_kind="op_invocation",
        op_id="demo-echo",
        input_payload_json={},
        details=None,
        origin_reference=None,
        created_by_actor="operator",
        created_at=now,
    )


def _create_job(repo: PostgresJobRepository, intent: JobIntent) -> JobRecord:
    now = datetime.now(UTC)
    return repo.create_job(
        job_intent_id=intent.id,
        schedule_type="one_time",
        state="active",
        timezone="UTC",
        definition_json={"type": "one_time", "run_at": now.isoformat()},
        next_run_at=now,
        retry_max_attempts=3,
        retry_backoff_strategy="exponential",
        retry_backoff_base_seconds=60,
        origin_trace_id="trace-int",
        origin_envelope_id="env-int",
        created_at=now,
    )


def test_intent_and_job_roundtrip(
    migrated_integration_settings,
) -> None:
    """Repository should persist intent and job with stable reads."""
    repo = _repo(migrated_integration_settings)

    intent = _create_intent(repo)
    assert intent.id
    assert intent.summary == "Integration test intent"

    fetched_intent = repo.get_job_intent(job_intent_id=intent.id)
    assert fetched_intent is not None
    assert fetched_intent.id == intent.id

    job = _create_job(repo, intent)
    assert job.id
    assert job.state.value == "active"
    assert job.schedule_type.value == "one_time"

    fetched_job = repo.get_job(job_id=job.id)
    assert fetched_job is not None
    assert fetched_job.job_intent_id == intent.id


def test_execution_lifecycle(
    migrated_integration_settings,
) -> None:
    """Repository should create, update, and list executions."""
    repo = _repo(migrated_integration_settings)
    now = datetime.now(UTC)

    intent = _create_intent(repo)
    job = _create_job(repo, intent)

    execution = repo.create_execution(
        job_id=job.id,
        job_intent_id=intent.id,
        scheduled_for=now,
        status="queued",
        attempt_number=1,
        max_attempts=3,
        retry_backoff_strategy="exponential",
        trace_id="trace-exec-int",
        parent_envelope_id="env-exec-int",
        trigger_source="scheduler",
        created_at=now,
    )
    assert execution.id
    assert execution.status.value == "queued"

    repo.update_execution_status(
        execution_id=execution.id,
        status="running",
        started_at=now,
        finished_at=None,
        retry_after=None,
        error_message=None,
        error_code=None,
        attempt_number=None,
    )

    fetched = repo.get_execution(execution_id=execution.id)
    assert fetched is not None
    assert fetched.status.value == "running"
    assert fetched.started_at is not None

    results = repo.list_executions(job_id=job.id, limit=10, cursor=None)
    assert any(e.id == execution.id for e in results)
