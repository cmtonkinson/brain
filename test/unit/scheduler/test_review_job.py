"""Unit tests for the schedule review job."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from models import (
    ReviewIssueTypeEnum,
    ReviewItem,
    ReviewSeverityEnum,
)
from scheduler.data_access import (
    ActorContext,
    ExecutionActorContext,
    ExecutionCreateInput,
    ExecutionUpdateInput,
    ScheduleCreateInput,
    ScheduleDefinitionInput,
    TaskIntentInput,
    create_execution,
    create_schedule,
    create_task_intent,
    update_execution,
    pause_schedule,
)
from scheduler.review_job import ReviewJob, ReviewJobConfig


def _actor_context() -> ActorContext:
    """Return a default actor context for schedule mutations."""
    return ActorContext(
        actor_type="test",
        actor_id="test-1",
        channel="test",
        trace_id="trace-1",
    )


def _execution_actor_context() -> ExecutionActorContext:
    """Return a default actor context for execution mutations."""
    return ExecutionActorContext(
        actor_type="test",
        actor_id="test-1",
        channel="test",
        trace_id="trace-1",
        request_id="req-1",
        actor_context="test",
    )


def test_review_job_detects_orphaned_schedules(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure the review job identifies orphaned schedules."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    # 25 hours ago (default grace period is 24h)
    orphan_time = now - timedelta(hours=25)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Orphaned"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=orphan_time + timedelta(minutes=1)),
            ),
            actor,
            now=orphan_time,
        )
        # Manually backdate next_run_at to simulate orphan status
        schedule.next_run_at = orphan_time - timedelta(minutes=1)
        session.flush()
        session.commit()

        job = ReviewJob(session, ReviewJobConfig())
        output = job.run(now=now)

        assert output.orphaned_count == 1
        assert output.failing_count == 0
        assert output.ignored_count == 0

        items = session.query(ReviewItem).filter(ReviewItem.review_output_id == output.id).all()
        assert len(items) == 1
        assert items[0].issue_type == ReviewIssueTypeEnum.orphaned
        assert items[0].schedule_id == schedule.id
        assert items[0].severity == ReviewSeverityEnum.high


def test_review_job_detects_failing_schedules(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure the review job identifies failing schedules."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    exec_actor = _execution_actor_context()
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Failing"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="hour"),
            ),
            actor,
            now=now,
        )

        # Create 3 failures (threshold is 3)
        for i in range(3):
            execution = create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=now - timedelta(hours=i + 1),
                    status="queued",
                ),
                exec_actor,
                now=now,
            )
            update_execution(
                session,
                execution.id,
                ExecutionUpdateInput(
                    status="failed",
                    failure_count=1,
                    last_error_message="Something went wrong",
                ),
                exec_actor,
                now=now,
            )

        # Manually update schedule to reflect failures since data_access doesn't auto-aggregate yet?
        # Actually data_access.update_execution DOES NOT update the schedule.
        # But data_access.update_schedule DOES.
        # The query service for failing schedules relies on Schedule table fields: last_run_status, failure_count.
        # We need to update the schedule to match the state we want to test.
        # In a real system, the dispatcher/runner would update the schedule after execution finishes.
        from scheduler.data_access import update_schedule, ScheduleUpdateInput

        update_schedule(
            session,
            schedule.id,
            ScheduleUpdateInput(
                last_run_status="failed",
                failure_count=3,
                last_execution_id=execution.id,
                last_run_at=now - timedelta(minutes=5),
            ),
            actor,
            now=now,
        )

        session.commit()

        job = ReviewJob(session, ReviewJobConfig())
        output = job.run(now=now)

        assert output.failing_count == 1
        items = session.query(ReviewItem).filter(ReviewItem.review_output_id == output.id).all()
        assert len(items) == 1
        assert items[0].issue_type == ReviewIssueTypeEnum.failing
        assert items[0].severity == ReviewSeverityEnum.medium
        assert items[0].last_error_message == "Something went wrong"


def test_review_job_detects_ignored_schedules(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure the review job identifies ignored (stale paused) schedules."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    # 31 days ago (default ignored age is 30d)
    ignored_time = now - timedelta(days=31)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Ignored"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now),  # irrelevant for paused
            ),
            actor,
            now=ignored_time,
        )
        # Pause it long ago
        pause_schedule(session, schedule.id, actor, now=ignored_time)
        session.commit()

        job = ReviewJob(session, ReviewJobConfig())
        output = job.run(now=now)

        assert output.ignored_count == 1
        items = session.query(ReviewItem).filter(ReviewItem.review_output_id == output.id).all()
        assert len(items) == 1
        assert items[0].issue_type == ReviewIssueTypeEnum.ignored
        assert items[0].severity == ReviewSeverityEnum.low
