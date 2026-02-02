"""Tests for stage-level retry controls."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from ingestion.retry import RetryPolicy, check_should_retry_stage
from models import Ingestion, IngestionStageRun


def _create_ingestion(session_factory, *, now) -> UUID:
    """Create a test ingestion and return its ID."""
    with session_factory() as session:
        ing = Ingestion(
            source_type="test",
            source_uri="test://retry",
            source_actor="test",
            status="queued",
            created_at=now,
            last_error=None,
        )
        session.add(ing)
        session.flush()
        ingestion_id = ing.id
        session.commit()
    return ingestion_id


def _create_stage_run(session_factory, ingestion_id: UUID, stage: str, status: str, *, now) -> None:
    """Create a stage run record."""
    with session_factory() as session:
        run = IngestionStageRun(
            ingestion_id=ingestion_id,
            stage=stage,
            status=status,
            error="test error" if status == "failed" else None,
            started_at=now,
            finished_at=now,
            created_at=now,
        )
        session.add(run)
        session.commit()


def test_retry_policy_allows_first_attempt(sqlite_session_factory):
    """Stage with no prior runs is allowed to run."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)

    policy = RetryPolicy(session_factory=sqlite_session_factory)
    decision = policy.should_run_stage(str(ingestion_id), "extract")

    assert decision.should_run is True
    assert decision.reason is not None
    assert "no prior stage run" in decision.reason


def test_retry_policy_skips_successful_stage(sqlite_session_factory):
    """Stage that already succeeded is skipped on retry."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)

    # Create successful stage run
    _create_stage_run(sqlite_session_factory, ingestion_id, "extract", "success", now=now)

    policy = RetryPolicy(session_factory=sqlite_session_factory)
    decision = policy.should_run_stage(str(ingestion_id), "extract")

    assert decision.should_run is False
    assert decision.reason is not None
    assert "already succeeded" in decision.reason


def test_retry_policy_allows_failed_stage_retry(sqlite_session_factory):
    """Failed stage can be retried."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)

    # Create failed stage run
    _create_stage_run(sqlite_session_factory, ingestion_id, "extract", "failed", now=now)

    policy = RetryPolicy(session_factory=sqlite_session_factory)
    decision = policy.should_run_stage(str(ingestion_id), "extract")

    assert decision.should_run is True
    assert decision.reason is not None
    assert "retrying failed stage" in decision.reason


def test_retry_policy_allows_skipped_stage_retry(sqlite_session_factory):
    """Skipped stage can be retried."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)

    # Create skipped stage run
    _create_stage_run(sqlite_session_factory, ingestion_id, "extract", "skipped", now=now)

    policy = RetryPolicy(session_factory=sqlite_session_factory)
    decision = policy.should_run_stage(str(ingestion_id), "extract")

    assert decision.should_run is True
    assert decision.reason is not None
    assert "retrying skipped stage" in decision.reason


def test_retry_does_not_rerun_earlier_successful_stages(sqlite_session_factory):
    """Retrying a failed stage does not rerun earlier successful stages."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)

    # Stage 1 succeeded
    _create_stage_run(sqlite_session_factory, ingestion_id, "store", "success", now=now)

    # Stage 2 succeeded
    _create_stage_run(sqlite_session_factory, ingestion_id, "extract", "success", now=now)

    # Stage 3 failed
    _create_stage_run(sqlite_session_factory, ingestion_id, "normalize", "failed", now=now)

    policy = RetryPolicy(session_factory=sqlite_session_factory)

    # Stage 1 should NOT run (already succeeded)
    decision_s1 = policy.should_run_stage(str(ingestion_id), "store")
    assert decision_s1.should_run is False
    assert decision_s1.reason is not None
    assert "already succeeded" in decision_s1.reason

    # Stage 2 should NOT run (already succeeded)
    decision_s2 = policy.should_run_stage(str(ingestion_id), "extract")
    assert decision_s2.should_run is False
    assert decision_s2.reason is not None
    assert "already succeeded" in decision_s2.reason

    # Stage 3 SHOULD run (failed)
    decision_s3 = policy.should_run_stage(str(ingestion_id), "normalize")
    assert decision_s3.should_run is True
    assert decision_s3.reason is not None
    assert "retrying failed stage" in decision_s3.reason


def test_check_should_retry_stage_convenience_function(sqlite_session_factory):
    """Convenience function works correctly."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)

    # Use convenience function
    decision = check_should_retry_stage(
        str(ingestion_id), "extract", session_factory=sqlite_session_factory
    )

    assert decision.should_run is True
    assert decision.reason is not None
    assert "no prior stage run" in decision.reason


def test_multiple_retries_append_records(sqlite_session_factory):
    """Multiple retry attempts create separate stage run records."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)

    # First attempt fails
    _create_stage_run(sqlite_session_factory, ingestion_id, "extract", "failed", now=now)

    # Second attempt fails
    later = datetime(2025, 1, 2, 1, 0, tzinfo=timezone.utc)
    _create_stage_run(sqlite_session_factory, ingestion_id, "extract", "failed", now=later)

    # Third attempt succeeds
    even_later = datetime(2025, 1, 2, 2, 0, tzinfo=timezone.utc)
    _create_stage_run(sqlite_session_factory, ingestion_id, "extract", "success", now=even_later)

    # Verify all three runs exist
    with sqlite_session_factory() as session:
        runs = (
            session.query(IngestionStageRun)
            .filter(
                IngestionStageRun.ingestion_id == ingestion_id,
                IngestionStageRun.stage == "extract",
            )
            .order_by(IngestionStageRun.created_at)
            .all()
        )
        assert len(runs) == 3
        assert runs[0].status == "failed"
        assert runs[1].status == "failed"
        assert runs[2].status == "success"

    # After success, stage should not run again
    policy = RetryPolicy(session_factory=sqlite_session_factory)
    decision = policy.should_run_stage(str(ingestion_id), "extract")
    assert decision.should_run is False
    assert decision.reason is not None
    assert "already succeeded" in decision.reason
