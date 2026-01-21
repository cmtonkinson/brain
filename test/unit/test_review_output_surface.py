"""Unit and integration tests for the review output inspection surface."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from models import ReviewIssueTypeEnum, ReviewItem, ReviewOutput, ReviewSeverityEnum
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
    update_schedule,
    ScheduleUpdateInput,
)
from scheduler.review_job import ReviewJob, ReviewJobConfig
from scheduler.schedule_query_service import ScheduleQueryServiceImpl
from scheduler.schedule_service_interface import (
    ExecutionGetRequest,
    ReviewOutputGetRequest,
    ReviewOutputListRequest,
    ScheduleGetRequest,
)


def _actor_context() -> ActorContext:
    """Return a default actor context for schedule mutations."""
    return ActorContext(
        actor_type="human",
        actor_id="user-1",
        channel="signal",
        trace_id="trace-123",
        request_id=None,
        reason="testing",
    )


def _execution_actor_context() -> ExecutionActorContext:
    """Return a default actor context for execution records."""
    return ExecutionActorContext(
        actor_type="scheduled",
        actor_id=None,
        channel="scheduled",
        trace_id="trace-exec-001",
        request_id=None,
        actor_context="scheduled-envelope",
    )


class TestReviewOutputList:
    """Tests for review output list filtering and pagination."""

    def test_list_review_outputs_filters_by_severity_and_date_range(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure review output list filters by severity and date range."""
        actor = _actor_context()
        exec_actor = _execution_actor_context()
        now = datetime(2025, 2, 1, 12, 0, tzinfo=timezone.utc)
        earlier = now - timedelta(days=2)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(session, TaskIntentInput(summary="Review list"), actor)
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="one_time",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(run_at=now),
                ),
                actor,
                now=earlier,
            )
            execution = create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=earlier,
                ),
                exec_actor,
                now=earlier,
            )

            output_high = ReviewOutput(
                job_execution_id=execution.id,
                window_start=earlier,
                window_end=earlier,
                orphan_grace_period_seconds=86400,
                consecutive_failure_threshold=3,
                stale_failure_age_seconds=604800,
                ignored_pause_age_seconds=2592000,
                orphaned_count=1,
                failing_count=0,
                ignored_count=0,
                created_at=earlier,
            )
            session.add(output_high)
            session.flush()
            session.add(
                ReviewItem(
                    review_output_id=output_high.id,
                    schedule_id=schedule.id,
                    task_intent_id=intent.id,
                    execution_id=execution.id,
                    issue_type=ReviewIssueTypeEnum.orphaned,
                    severity=ReviewSeverityEnum.high,
                    description="Orphaned schedule",
                    last_error_message=None,
                    created_at=earlier,
                )
            )

            output_low = ReviewOutput(
                window_start=now,
                window_end=now,
                orphan_grace_period_seconds=86400,
                consecutive_failure_threshold=3,
                stale_failure_age_seconds=604800,
                ignored_pause_age_seconds=2592000,
                orphaned_count=0,
                failing_count=0,
                ignored_count=1,
                created_at=now,
            )
            session.add(output_low)
            session.flush()
            session.add(
                ReviewItem(
                    review_output_id=output_low.id,
                    schedule_id=schedule.id,
                    task_intent_id=intent.id,
                    execution_id=None,
                    issue_type=ReviewIssueTypeEnum.ignored,
                    severity=ReviewSeverityEnum.low,
                    description="Ignored schedule",
                    last_error_message=None,
                    created_at=now,
                )
            )
            session.commit()

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.list_review_outputs(
            ReviewOutputListRequest(
                severity=ReviewSeverityEnum.high,
                created_after=earlier - timedelta(hours=1),
                created_before=earlier + timedelta(hours=1),
                limit=10,
            )
        )

        assert len(result.review_outputs) == 1
        review_output = result.review_outputs[0]
        assert review_output.job_execution_id is not None
        assert review_output.criteria.orphan_grace_period_seconds == 86400
        assert review_output.orphaned_count == 1


class TestReviewOutputDetail:
    """Tests for review output detail queries."""

    def test_get_review_output_returns_items_with_links(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure review output detail returns linked review items."""
        actor = _actor_context()
        exec_actor = _execution_actor_context()
        now = datetime(2025, 2, 2, 9, 30, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(session, TaskIntentInput(summary="Detail view"), actor)
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
            execution = create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=now,
                ),
                exec_actor,
                now=now,
            )

            output = ReviewOutput(
                job_execution_id=None,
                window_start=now,
                window_end=now,
                orphan_grace_period_seconds=86400,
                consecutive_failure_threshold=3,
                stale_failure_age_seconds=604800,
                ignored_pause_age_seconds=2592000,
                orphaned_count=0,
                failing_count=1,
                ignored_count=0,
                created_at=now,
            )
            session.add(output)
            session.flush()
            session.add(
                ReviewItem(
                    review_output_id=output.id,
                    schedule_id=schedule.id,
                    task_intent_id=intent.id,
                    execution_id=execution.id,
                    issue_type=ReviewIssueTypeEnum.failing,
                    severity=ReviewSeverityEnum.medium,
                    description="Failing schedule",
                    last_error_message="oops",
                    created_at=now,
                )
            )
            session.commit()
            output_id = output.id
            schedule_id = schedule.id
            execution_id = execution.id

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.get_review_output(ReviewOutputGetRequest(review_output_id=output_id))

        assert result.review_output.id == output_id
        assert result.review_output.criteria.consecutive_failure_threshold == 3
        assert len(result.review_items) == 1
        item = result.review_items[0]
        assert item.schedule_id == schedule_id
        assert item.execution_id == execution_id
        assert item.severity == ReviewSeverityEnum.medium


class TestReviewOutputSurfaceIntegration:
    """Integration tests for review output linkage across schedules and executions."""

    def test_review_output_links_schedule_and_execution(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Verify review outputs link to schedules and executions via inspection APIs."""
        actor = _actor_context()
        exec_actor = _execution_actor_context()
        now = datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(session, TaskIntentInput(summary="Integration"), actor)
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
            execution = create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=now - timedelta(hours=1),
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
                    last_error_message="Boom",
                ),
                exec_actor,
                now=now,
            )
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
            session.commit()
            output_id = output.id
            schedule_id = schedule.id
            execution_id = execution.id

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        review_result = service.get_review_output(
            ReviewOutputGetRequest(review_output_id=output_id)
        )
        assert len(review_result.review_items) == 1
        item = review_result.review_items[0]
        assert item.schedule_id == schedule_id
        assert item.execution_id == execution_id

        schedule_result = service.get_schedule(ScheduleGetRequest(schedule_id=item.schedule_id))
        execution_result = service.get_execution(
            ExecutionGetRequest(execution_id=item.execution_id)
        )
        assert schedule_result.schedule.id == schedule_id
        assert execution_result.execution.id == execution_id
