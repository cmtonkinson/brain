"""Tests for ingestion stage outcome recording functionality."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ingestion.stage_recorder import StageRecorder, record_stage_failure
from models import Ingestion, IngestionStageRun


def _create_ingestion(session_factory, *, now) -> UUID:
    """Create a test ingestion and return its ID."""
    with session_factory() as session:
        ing = Ingestion(
            source_type="test",
            source_uri="test://example",
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


def test_record_stage_success(sqlite_session_factory):
    """Successful stage creates a success record with timing data."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)
    recorder = StageRecorder(session_factory=sqlite_session_factory)

    with recorder.record_stage(ingestion_id, "extract", now=now) as record:
        assert record.ingestion_id == ingestion_id
        assert record.stage == "extract"
        assert record.status == "running"
        assert record.error is None
        assert record.started_at == now
        assert record.finished_at is None

    # Verify the stage run was created and marked as success
    with sqlite_session_factory() as session:
        stage_run = (
            session.query(IngestionStageRun)
            .filter(
                IngestionStageRun.ingestion_id == ingestion_id,
                IngestionStageRun.stage == "extract",
            )
            .first()
        )
        assert stage_run is not None
        assert stage_run.status == "success"
        assert stage_run.error is None
        assert stage_run.started_at is not None
        assert stage_run.finished_at is not None
        assert stage_run.created_at is not None
        # Timing should be consistent
        assert stage_run.finished_at >= stage_run.started_at


def test_record_stage_failure(sqlite_session_factory):
    """Failed stage creates a failed record with error message."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)
    recorder = StageRecorder(session_factory=sqlite_session_factory)

    with pytest.raises(RuntimeError, match="test error"):
        with recorder.record_stage(ingestion_id, "extract", now=now):
            raise RuntimeError("test error")

    # Verify the stage run was created and marked as failed
    with sqlite_session_factory() as session:
        stage_run = (
            session.query(IngestionStageRun)
            .filter(
                IngestionStageRun.ingestion_id == ingestion_id,
                IngestionStageRun.stage == "extract",
            )
            .first()
        )
        assert stage_run is not None
        assert stage_run.status == "failed"
        assert stage_run.error == "test error"
        assert stage_run.started_at is not None
        assert stage_run.finished_at is not None
        assert stage_run.finished_at >= stage_run.started_at

        # Verify ingestion status was updated to failed
        ingestion_record = session.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
        assert ingestion_record is not None
        assert ingestion_record.status == "failed"
        assert ingestion_record.last_error == "test error"


def test_record_skipped_stage(sqlite_session_factory):
    """Skipped stage creates a skipped record with reason."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)
    recorder = StageRecorder(session_factory=sqlite_session_factory)

    result = recorder.record_skipped_stage(
        ingestion_id,
        "extract",
        "retry policy: max failures exceeded",
        now=now,
    )

    assert result.ingestion_id == ingestion_id
    assert result.stage == "extract"
    assert result.status == "skipped"
    assert result.error == "retry policy: max failures exceeded"
    assert result.started_at == now
    assert result.finished_at == now

    # Verify the stage run was created
    with sqlite_session_factory() as session:
        stage_run = (
            session.query(IngestionStageRun)
            .filter(
                IngestionStageRun.ingestion_id == ingestion_id,
                IngestionStageRun.stage == "extract",
            )
            .first()
        )
        assert stage_run is not None
        assert stage_run.status == "skipped"
        assert stage_run.error == "retry policy: max failures exceeded"
        assert stage_run.started_at is not None
        assert stage_run.finished_at is not None
        assert stage_run.finished_at >= stage_run.started_at


def test_record_stage_failure_helper(sqlite_session_factory):
    """record_stage_failure helper creates a failed stage run."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)

    result = record_stage_failure(
        ingestion_id,
        "extract",
        "5 artifact(s) failed extraction",
        session_factory=sqlite_session_factory,
        now=now,
    )

    assert result.ingestion_id == ingestion_id
    assert result.stage == "extract"
    assert result.status == "failed"
    assert result.error == "5 artifact(s) failed extraction"
    assert result.started_at == now
    assert result.finished_at == now

    # Verify the stage run was created
    with sqlite_session_factory() as session:
        stage_run = (
            session.query(IngestionStageRun)
            .filter(
                IngestionStageRun.ingestion_id == ingestion_id,
                IngestionStageRun.stage == "extract",
            )
            .first()
        )
        assert stage_run is not None
        assert stage_run.status == "failed"
        assert stage_run.error == "5 artifact(s) failed extraction"

        # Verify ingestion status was updated to failed
        ingestion_record = session.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
        assert ingestion_record is not None
        assert ingestion_record.status == "failed"
        assert ingestion_record.last_error == "5 artifact(s) failed extraction"


def test_record_stage1_updates_ingestion_to_running(sqlite_session_factory):
    """Stage 1 (store) updates ingestion status to running on start."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)
    recorder = StageRecorder(session_factory=sqlite_session_factory)

    with recorder.record_stage(ingestion_id, "store", now=now):
        # Verify ingestion status was updated to running
        with sqlite_session_factory() as session:
            ingestion_record = session.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
            assert ingestion_record is not None
            assert ingestion_record.status == "running"


def test_record_stage4_updates_ingestion_to_complete(sqlite_session_factory):
    """Stage 4 (anchor) updates ingestion status to complete on success."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)
    recorder = StageRecorder(session_factory=sqlite_session_factory)

    # First set ingestion to running
    with sqlite_session_factory() as session:
        ingestion_record = session.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
        ingestion_record.status = "running"
        session.commit()

    with recorder.record_stage(ingestion_id, "anchor", now=now):
        pass

    # Verify ingestion status was updated to complete
    with sqlite_session_factory() as session:
        ingestion_record = session.query(Ingestion).filter(Ingestion.id == ingestion_id).first()
        assert ingestion_record is not None
        assert ingestion_record.status == "complete"


def test_multiple_stage_runs_for_retries(sqlite_session_factory):
    """Multiple stage runs can be recorded for the same ingestion/stage (retries)."""
    now = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)
    recorder = StageRecorder(session_factory=sqlite_session_factory)

    # First attempt fails
    with pytest.raises(RuntimeError):
        with recorder.record_stage(ingestion_id, "extract", now=now):
            raise RuntimeError("first attempt failed")

    # Second attempt succeeds
    later = datetime(2025, 1, 2, 1, 0, tzinfo=timezone.utc)
    with recorder.record_stage(ingestion_id, "extract", now=later):
        pass

    # Verify both stage runs were recorded
    with sqlite_session_factory() as session:
        stage_runs = (
            session.query(IngestionStageRun)
            .filter(
                IngestionStageRun.ingestion_id == ingestion_id,
                IngestionStageRun.stage == "extract",
            )
            .order_by(IngestionStageRun.created_at)
            .all()
        )
        assert len(stage_runs) == 2
        assert stage_runs[0].status == "failed"
        assert stage_runs[0].error == "first attempt failed"
        assert stage_runs[1].status == "success"
        assert stage_runs[1].error is None


def test_record_stage_timing_accuracy(sqlite_session_factory):
    """Stage run timing fields accurately reflect start and finish times."""
    now = datetime(2025, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
    ingestion_id = _create_ingestion(sqlite_session_factory, now=now)
    start_time = datetime(2025, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
    finish_time = datetime(2025, 1, 2, 0, 5, 30, tzinfo=timezone.utc)
    recorder = StageRecorder(session_factory=sqlite_session_factory)

    # Manually control timing using _start_stage_run and _finish_stage_run
    run_id = recorder._start_stage_run(ingestion_id, "extract", start_time)
    recorder._finish_stage_run(run_id, "success", None, finish_time)

    # Verify timing data
    with sqlite_session_factory() as session:
        stage_run = session.query(IngestionStageRun).filter(IngestionStageRun.id == run_id).first()
        assert stage_run is not None
        assert stage_run.started_at is not None
        assert stage_run.finished_at is not None
        assert stage_run.created_at is not None
        # Verify duration makes sense (allow small rounding errors from DB storage)
        duration = (stage_run.finished_at - stage_run.started_at).total_seconds()
        assert abs(duration - 330) < 1  # 5 minutes 30 seconds, within 1 second tolerance
