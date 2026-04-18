"""Tests for Ingestion Service domain logic."""

from __future__ import annotations

from datetime import UTC, datetime

from services.control.ingestion.domain import (
    STAGE_ORDER,
    STAGE_SET,
    StageRunRecord,
    StageRunStatus,
    stage_replay_decision,
)


def _make_stage_run(
    *,
    status: str,
    created_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> StageRunRecord:
    """Build a minimal StageRunRecord for testing replay decisions."""
    ts = created_at or datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    return StageRunRecord(
        id="01HX1111111111111111111111",
        ingestion_id="01HX2222222222222222222222",
        stage="store",
        status=StageRunStatus(status),
        error=None,
        started_at=ts,
        finished_at=finished_at or ts,
        created_at=ts,
    )


class TestStageConstants:
    def test_stage_order_is_deterministic(self) -> None:
        assert list(STAGE_ORDER) == ["store", "extract", "normalize", "anchor"]

    def test_stage_set_covers_all_stages(self) -> None:
        assert STAGE_SET == {"store", "extract", "normalize", "anchor"}

    def test_stage_order_and_set_agree(self) -> None:
        assert frozenset(STAGE_ORDER) == STAGE_SET


class TestStageReplayDecision:
    def test_no_prior_run_should_run(self) -> None:
        decision = stage_replay_decision(stage_runs=[])
        assert decision.should_run is True
        assert "no prior run" in decision.reason

    def test_succeeded_should_not_run(self) -> None:
        run = _make_stage_run(status="success")
        decision = stage_replay_decision(stage_runs=[run])
        assert decision.should_run is False
        assert "already succeeded" in decision.reason

    def test_failed_should_run(self) -> None:
        run = _make_stage_run(status="failed")
        decision = stage_replay_decision(stage_runs=[run])
        assert decision.should_run is True
        assert "failed" in decision.reason

    def test_skipped_should_run(self) -> None:
        run = _make_stage_run(status="skipped")
        decision = stage_replay_decision(stage_runs=[run])
        assert decision.should_run is True
        assert "skipped" in decision.reason

    def test_uses_most_recent_run_when_multiple_exist(self) -> None:
        old_failed = _make_stage_run(
            status="failed",
            created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        recent_success = _make_stage_run(
            status="success",
            created_at=datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
        )
        decision = stage_replay_decision(stage_runs=[old_failed, recent_success])
        assert decision.should_run is False

    def test_most_recent_failed_after_older_success(self) -> None:
        old_success = _make_stage_run(
            status="success",
            created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        recent_failed = _make_stage_run(
            status="failed",
            created_at=datetime(2026, 1, 3, 0, 0, 0, tzinfo=UTC),
        )
        decision = stage_replay_decision(stage_runs=[old_success, recent_failed])
        assert decision.should_run is True
