"""Integration tests for the review job outputs."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models import ReviewItem, ReviewOutput
from scheduler import data_access
from scheduler.review_job import ReviewJob, ReviewJobConfig


def _seed_schedule(session: Session, summary: str) -> data_access.Schedule:
    """Create an interval schedule used for review job scenarios."""
    actor = data_access.ActorContext(
        actor_type="human",
        actor_id="review-test",
        channel="cli",
        trace_id="trace-review",
        request_id="req-review",
    )
    _, schedule = data_access.create_schedule_with_intent(
        session,
        data_access.ScheduleCreateWithIntentInput(
            task_intent=data_access.TaskIntentInput(summary=summary),
            schedule_type="interval",
            timezone="UTC",
            definition=data_access.ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        actor,
    )
    session.flush()
    return schedule


def test_review_job_records_orphaned_failing_and_ignored_schedules(
    sqlite_session_factory,
) -> None:
    """Ensure review job persists expected review outputs for flagged schedules."""
    now = datetime(2025, 6, 1, 12, tzinfo=timezone.utc)
    config = ReviewJobConfig(
        orphan_grace_period=timedelta(minutes=1),
        consecutive_failure_threshold=1,
        stale_failure_age=timedelta(minutes=1),
        ignored_pause_age=timedelta(minutes=1),
    )

    orphan_id = failing_id = ignored_id = None
    failing_task_intent_id = None
    with closing(sqlite_session_factory()) as session:
        orphan = _seed_schedule(session, "Orphaned schedule")
        failing = _seed_schedule(session, "Failing schedule")
        ignored = _seed_schedule(session, "Ignored schedule")
        session.commit()
        orphan_id = orphan.id
        failing_id = failing.id
        failing_task_intent_id = failing.task_intent_id
        ignored_id = ignored.id

    actor = data_access.ActorContext(
        actor_type="human",
        actor_id="review-updater",
        channel="cli",
        trace_id="trace-review-update",
        request_id="req-review-update",
    )

    failure_execution_id = None
    with closing(sqlite_session_factory()) as session:
        data_access.update_schedule(
            session,
            orphan_id,
            data_access.ScheduleUpdateInput(next_run_at=now - timedelta(minutes=5), state="active"),
            actor,
            now=now - timedelta(minutes=5),
        )
        failure_execution = data_access.create_execution(
            session,
            data_access.ExecutionCreateInput(
                task_intent_id=failing_task_intent_id,
                schedule_id=failing_id,
                scheduled_for=now - timedelta(minutes=10),
                status="failed",
                failure_count=1,
            ),
            data_access.ExecutionActorContext(
                actor_type="scheduled",
                actor_id=None,
                channel="scheduled",
                trace_id="trace-failing-exec",
                request_id="req-failing-exec",
                actor_context="scheduled|review",
            ),
        )
        data_access.update_schedule(
            session,
            failing_id,
            data_access.ScheduleUpdateInput(
                last_run_at=now - timedelta(minutes=2),
                last_run_status="failed",
                failure_count=3,
                last_execution_id=failure_execution.id,
            ),
            actor,
            now=now - timedelta(minutes=2),
        )
        data_access.update_schedule(
            session,
            ignored_id,
            data_access.ScheduleUpdateInput(state="paused"),
            actor,
            now=now - timedelta(minutes=5),
        )
        session.commit()
        failure_execution_id = failure_execution.id

    assert failure_execution_id is not None
    with closing(sqlite_session_factory()) as session:
        review_job = ReviewJob(session, config=config)
        output = review_job.run(now=now)
        session.commit()
        output_id = output.id

    with closing(sqlite_session_factory()) as session:
        persisted = session.query(ReviewOutput).filter(ReviewOutput.id == output_id).one()
        assert persisted.orphaned_count == 1
        assert persisted.failing_count == 1
        assert persisted.ignored_count == 1
        items = (
            session.query(ReviewItem)
            .filter(ReviewItem.review_output_id == output_id)
            .order_by(ReviewItem.issue_type.asc())
            .all()
        )

    assert len(items) == 3
    failing_items = [item for item in items if item.issue_type == "failing"]
    assert failing_items
    assert failing_items[0].execution_id == failure_execution_id
    orphan_items = [item for item in items if item.issue_type == "orphaned"]
    assert orphan_items
    ignored_items = [item for item in items if item.issue_type == "ignored"]
    assert ignored_items
