"""Unit tests for the schedule query service (inspection API).

Tests cover:
- Schedule inspection with list and detail views
- Execution inspection with list and detail views
- Filtering by status, time range, schedule_id
- Pagination with cursor support
- Audit linkage visibility in responses
- Error handling for not found and invalid filters
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

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
)
from scheduler.schedule_query_service import ScheduleQueryServiceImpl
from scheduler.schedule_service_interface import (
    ExecutionGetRequest,
    ExecutionListRequest,
    ExecutionAuditGetRequest,
    ScheduleGetRequest,
    ScheduleListRequest,
    ScheduleNotFoundError,
    ScheduleServiceError,
    TaskIntentGetRequest,
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


def _execution_actor_context(trace_id: str = "trace-exec-001") -> ExecutionActorContext:
    """Return a default actor context for execution records."""
    return ExecutionActorContext(
        actor_type="scheduled",
        actor_id=None,
        channel="scheduled",
        trace_id=trace_id,
        request_id=None,
        actor_context="scheduled-envelope",
    )


# ============================================================================
# Schedule Inspection Tests
# ============================================================================


class TestScheduleGetDetail:
    """Tests for get_schedule detail view."""

    def test_get_schedule_returns_schedule_with_task_intent(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure get_schedule returns schedule view with linked task intent."""
        actor = _actor_context()
        now = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session,
                TaskIntentInput(
                    summary="Daily standup reminder",
                    details="Remind team of daily standup at 9am",
                    origin_reference="signal:thread-1",
                ),
                actor,
            )
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="interval",
                    timezone="America/New_York",
                    definition=ScheduleDefinitionInput(
                        interval_count=1, interval_unit="day"
                    ),
                ),
                actor,
                now=now,
            )
            session.commit()
            schedule_id = schedule.id
            intent_id = intent.id

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.get_schedule(ScheduleGetRequest(schedule_id=schedule_id))

        assert result.schedule.id == schedule_id
        assert result.schedule.task_intent_id == intent_id
        assert result.schedule.schedule_type == "interval"
        assert result.schedule.state == "active"
        assert result.schedule.timezone == "America/New_York"
        assert result.schedule.definition.interval_count == 1
        assert result.schedule.definition.interval_unit == "day"
        assert result.task_intent.id == intent_id
        assert result.task_intent.summary == "Daily standup reminder"
        assert result.task_intent.details == "Remind team of daily standup at 9am"
        assert result.task_intent.origin_reference == "signal:thread-1"

    def test_get_schedule_not_found_raises_error(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure get_schedule raises ScheduleNotFoundError for missing schedule."""
        service = ScheduleQueryServiceImpl(sqlite_session_factory)

        with pytest.raises(ScheduleNotFoundError) as exc_info:
            service.get_schedule(ScheduleGetRequest(schedule_id=99999))

        assert exc_info.value.code == "not_found"
        assert "schedule not found" in str(exc_info.value)

    def test_get_schedule_includes_audit_linkage_fields(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure schedule view includes audit linkage fields."""
        actor = _actor_context()
        now = datetime(2025, 1, 2, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="one_time",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(run_at=now + timedelta(hours=1)),
                ),
                actor,
                now=now,
            )
            # Create an execution to link
            execution = create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=now + timedelta(hours=1),
                    status="queued",
                ),
                _execution_actor_context(),
            )
            # Update schedule's last_execution_id
            schedule.last_execution_id = execution.id
            session.commit()
            schedule_id = schedule.id
            execution_id = execution.id

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.get_schedule(ScheduleGetRequest(schedule_id=schedule_id))

        # Audit linkage fields
        assert result.schedule.last_execution_id == execution_id
        assert result.schedule.created_by_actor_type == "human"
        assert result.schedule.created_by_actor_id == "user-1"
        assert result.schedule.failure_count == 0


class TestScheduleList:
    """Tests for list_schedules with filtering and pagination."""

    def test_list_schedules_returns_all_when_no_filters(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_schedules returns all schedules with no filters."""
        actor = _actor_context()
        now = datetime(2025, 1, 3, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            for i in range(3):
                create_schedule(
                    session,
                    ScheduleCreateInput(
                        task_intent_id=intent.id,
                        schedule_type="one_time",
                        timezone="UTC",
                        definition=ScheduleDefinitionInput(
                            run_at=now + timedelta(hours=i + 1)
                        ),
                    ),
                    actor,
                    now=now,
                )
            session.commit()

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.list_schedules(ScheduleListRequest())

        assert len(result.schedules) == 3

    def test_list_schedules_filter_by_state(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_schedules filters by state correctly."""
        actor = _actor_context()
        now = datetime(2025, 1, 4, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            # Active schedule
            create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="interval",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        interval_count=1, interval_unit="day"
                    ),
                ),
                actor,
                now=now,
            )
            # Paused schedule (manually set state for test)
            paused = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="interval",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        interval_count=1, interval_unit="hour"
                    ),
                ),
                actor,
                now=now,
            )
            paused.state = "paused"
            session.commit()

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        active_result = service.list_schedules(ScheduleListRequest(state="active"))
        paused_result = service.list_schedules(ScheduleListRequest(state="paused"))

        assert len(active_result.schedules) == 1
        assert active_result.schedules[0].state == "active"
        assert len(paused_result.schedules) == 1
        assert paused_result.schedules[0].state == "paused"

    def test_list_schedules_filter_by_schedule_type(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_schedules filters by schedule_type correctly."""
        actor = _actor_context()
        now = datetime(2025, 1, 5, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="one_time",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(run_at=now + timedelta(hours=1)),
                ),
                actor,
                now=now,
            )
            create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="interval",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        interval_count=1, interval_unit="day"
                    ),
                ),
                actor,
                now=now,
            )
            session.commit()

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        one_time = service.list_schedules(ScheduleListRequest(schedule_type="one_time"))
        interval = service.list_schedules(ScheduleListRequest(schedule_type="interval"))

        assert len(one_time.schedules) == 1
        assert one_time.schedules[0].schedule_type == "one_time"
        assert len(interval.schedules) == 1
        assert interval.schedules[0].schedule_type == "interval"

    def test_list_schedules_filter_by_time_range(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_schedules filters by created_after and created_before."""
        actor = _actor_context()
        base_time = datetime(2025, 1, 6, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            for i in range(3):
                create_schedule(
                    session,
                    ScheduleCreateInput(
                        task_intent_id=intent.id,
                        schedule_type="one_time",
                        timezone="UTC",
                        definition=ScheduleDefinitionInput(
                            run_at=base_time + timedelta(hours=i + 5)
                        ),
                    ),
                    actor,
                    now=base_time + timedelta(hours=i),
                )
            session.commit()

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        after_result = service.list_schedules(
            ScheduleListRequest(created_after=base_time + timedelta(hours=1))
        )
        before_result = service.list_schedules(
            ScheduleListRequest(created_before=base_time + timedelta(hours=1))
        )

        assert len(after_result.schedules) == 2
        assert len(before_result.schedules) == 2

    def test_list_schedules_pagination_with_cursor(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_schedules pagination works with cursor."""
        actor = _actor_context()
        now = datetime(2025, 1, 7, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            for i in range(5):
                create_schedule(
                    session,
                    ScheduleCreateInput(
                        task_intent_id=intent.id,
                        schedule_type="one_time",
                        timezone="UTC",
                        definition=ScheduleDefinitionInput(
                            run_at=now + timedelta(hours=i + 1)
                        ),
                    ),
                    actor,
                    now=now,
                )
            session.commit()

        service = ScheduleQueryServiceImpl(sqlite_session_factory)

        # First page
        page1 = service.list_schedules(ScheduleListRequest(limit=2))
        assert len(page1.schedules) == 2
        assert page1.next_cursor is not None

        # Second page
        page2 = service.list_schedules(ScheduleListRequest(limit=2, cursor=page1.next_cursor))
        assert len(page2.schedules) == 2
        assert page2.next_cursor is not None

        # Third page
        page3 = service.list_schedules(ScheduleListRequest(limit=2, cursor=page2.next_cursor))
        assert len(page3.schedules) == 1
        assert page3.next_cursor is None

        # Verify no overlap
        all_ids = [s.id for s in page1.schedules + page2.schedules + page3.schedules]
        assert len(all_ids) == len(set(all_ids))

    def test_list_schedules_invalid_state_raises_error(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_schedules raises error for invalid state filter."""
        service = ScheduleQueryServiceImpl(sqlite_session_factory)

        with pytest.raises(ScheduleServiceError) as exc_info:
            service.list_schedules(ScheduleListRequest(state="invalid_state"))

        assert exc_info.value.code == "validation_error"

    def test_list_schedules_invalid_schedule_type_raises_error(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_schedules raises error for invalid schedule_type filter."""
        service = ScheduleQueryServiceImpl(sqlite_session_factory)

        with pytest.raises(ScheduleServiceError) as exc_info:
            service.list_schedules(ScheduleListRequest(schedule_type="invalid_type"))

        assert exc_info.value.code == "validation_error"


# ============================================================================
# Task Intent Inspection Tests
# ============================================================================


class TestTaskIntentGet:
    """Tests for get_task_intent detail view."""

    def test_get_task_intent_returns_complete_view(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure get_task_intent returns complete task intent view."""
        actor = _actor_context()

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session,
                TaskIntentInput(
                    summary="Important task",
                    details="Do something important",
                    origin_reference="signal:msg-123",
                ),
                actor,
            )
            session.commit()
            intent_id = intent.id

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.get_task_intent(TaskIntentGetRequest(task_intent_id=intent_id))

        assert result.task_intent.id == intent_id
        assert result.task_intent.summary == "Important task"
        assert result.task_intent.details == "Do something important"
        assert result.task_intent.origin_reference == "signal:msg-123"
        assert result.task_intent.creator_actor_type == "human"
        assert result.task_intent.creator_actor_id == "user-1"
        assert result.task_intent.creator_channel == "signal"

    def test_get_task_intent_not_found_raises_error(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure get_task_intent raises ScheduleNotFoundError for missing intent."""
        service = ScheduleQueryServiceImpl(sqlite_session_factory)

        with pytest.raises(ScheduleNotFoundError) as exc_info:
            service.get_task_intent(TaskIntentGetRequest(task_intent_id=99999))

        assert exc_info.value.code == "not_found"


# ============================================================================
# Execution Inspection Tests
# ============================================================================


class TestExecutionGetDetail:
    """Tests for get_execution detail view."""

    def test_get_execution_returns_complete_view(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure get_execution returns complete execution view."""
        actor = _actor_context()
        exec_actor = _execution_actor_context()
        now = datetime(2025, 1, 8, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="one_time",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(run_at=now),
                ),
                actor,
                now=now - timedelta(hours=1),
            )
            execution = create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=now,
                    status="queued",
                    max_attempts=3,
                ),
                exec_actor,
            )
            session.commit()
            execution_id = execution.id
            schedule_id = schedule.id
            intent_id = intent.id

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.get_execution(ExecutionGetRequest(execution_id=execution_id))

        assert result.execution.id == execution_id
        assert result.execution.schedule_id == schedule_id
        assert result.execution.task_intent_id == intent_id
        # Compare without timezone as SQLite doesn't preserve it
        assert result.execution.scheduled_for.replace(tzinfo=None) == now.replace(tzinfo=None)
        assert result.execution.status == "queued"
        assert result.execution.max_attempts == 3
        assert result.execution.actor_type == "scheduled"
        assert result.execution.trace_id == "trace-exec-001"

    def test_get_execution_not_found_raises_error(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure get_execution raises ScheduleNotFoundError for missing execution."""
        service = ScheduleQueryServiceImpl(sqlite_session_factory)

        with pytest.raises(ScheduleNotFoundError) as exc_info:
            service.get_execution(ExecutionGetRequest(execution_id=99999))

        assert exc_info.value.code == "not_found"
        assert "execution not found" in str(exc_info.value)


class TestExecutionList:
    """Tests for list_executions with filtering and pagination."""

    def test_list_executions_returns_all_when_no_filters(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_executions returns all executions with no filters."""
        actor = _actor_context()
        exec_actor = _execution_actor_context()
        now = datetime(2025, 1, 9, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="interval",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        interval_count=1, interval_unit="hour"
                    ),
                ),
                actor,
                now=now,
            )
            for i in range(3):
                create_execution(
                    session,
                    ExecutionCreateInput(
                        task_intent_id=intent.id,
                        schedule_id=schedule.id,
                        scheduled_for=now + timedelta(hours=i),
                        status="queued",
                    ),
                    _execution_actor_context(f"trace-{i}"),
                )
            session.commit()

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.list_executions(ExecutionListRequest())

        assert len(result.executions) == 3

    def test_list_executions_filter_by_schedule_id(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_executions filters by schedule_id correctly."""
        actor = _actor_context()
        now = datetime(2025, 1, 10, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            schedule1 = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="one_time",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(run_at=now + timedelta(hours=1)),
                ),
                actor,
                now=now,
            )
            schedule2 = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="one_time",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(run_at=now + timedelta(hours=2)),
                ),
                actor,
                now=now,
            )
            create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule1.id,
                    scheduled_for=now + timedelta(hours=1),
                    status="queued",
                ),
                _execution_actor_context("trace-s1"),
            )
            create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule2.id,
                    scheduled_for=now + timedelta(hours=2),
                    status="queued",
                ),
                _execution_actor_context("trace-s2"),
            )
            session.commit()
            schedule1_id = schedule1.id
            schedule2_id = schedule2.id

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result1 = service.list_executions(ExecutionListRequest(schedule_id=schedule1_id))
        result2 = service.list_executions(ExecutionListRequest(schedule_id=schedule2_id))

        assert len(result1.executions) == 1
        assert result1.executions[0].schedule_id == schedule1_id
        assert len(result2.executions) == 1
        assert result2.executions[0].schedule_id == schedule2_id

    def test_list_executions_filter_by_status(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_executions filters by status correctly."""
        actor = _actor_context()
        now = datetime(2025, 1, 11, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="interval",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        interval_count=1, interval_unit="hour"
                    ),
                ),
                actor,
                now=now,
            )
            exec_queued = create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=now,
                    status="queued",
                ),
                _execution_actor_context("trace-q"),
            )
            exec_succeeded = create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=now + timedelta(hours=1),
                    status="queued",
                ),
                _execution_actor_context("trace-s"),
            )
            # Update to succeeded
            update_execution(
                session,
                exec_succeeded.id,
                ExecutionUpdateInput(status="succeeded"),
                _execution_actor_context("trace-s-update"),
            )
            session.commit()

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        queued = service.list_executions(ExecutionListRequest(status="queued"))
        succeeded = service.list_executions(ExecutionListRequest(status="succeeded"))

        assert len(queued.executions) == 1
        assert queued.executions[0].status == "queued"
        assert len(succeeded.executions) == 1
        assert succeeded.executions[0].status == "succeeded"

    def test_list_executions_filter_by_time_range(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_executions filters by created_after and created_before."""
        actor = _actor_context()
        base_time = datetime(2025, 1, 12, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="interval",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        interval_count=1, interval_unit="hour"
                    ),
                ),
                actor,
                now=base_time,
            )
            for i in range(3):
                create_execution(
                    session,
                    ExecutionCreateInput(
                        task_intent_id=intent.id,
                        schedule_id=schedule.id,
                        scheduled_for=base_time + timedelta(hours=i),
                        status="queued",
                    ),
                    _execution_actor_context(f"trace-{i}"),
                    now=base_time + timedelta(hours=i),
                )
            session.commit()

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        after_result = service.list_executions(
            ExecutionListRequest(created_after=base_time + timedelta(hours=1))
        )
        before_result = service.list_executions(
            ExecutionListRequest(created_before=base_time + timedelta(hours=1))
        )

        assert len(after_result.executions) == 2
        assert len(before_result.executions) == 2

    def test_list_executions_pagination_with_cursor(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_executions pagination works with cursor."""
        actor = _actor_context()
        now = datetime(2025, 1, 13, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="interval",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        interval_count=1, interval_unit="hour"
                    ),
                ),
                actor,
                now=now,
            )
            for i in range(5):
                create_execution(
                    session,
                    ExecutionCreateInput(
                        task_intent_id=intent.id,
                        schedule_id=schedule.id,
                        scheduled_for=now + timedelta(hours=i),
                        status="queued",
                    ),
                    _execution_actor_context(f"trace-{i}"),
                )
            session.commit()

        service = ScheduleQueryServiceImpl(sqlite_session_factory)

        # First page
        page1 = service.list_executions(ExecutionListRequest(limit=2))
        assert len(page1.executions) == 2
        assert page1.next_cursor is not None

        # Second page
        page2 = service.list_executions(
            ExecutionListRequest(limit=2, cursor=page1.next_cursor)
        )
        assert len(page2.executions) == 2
        assert page2.next_cursor is not None

        # Third page
        page3 = service.list_executions(
            ExecutionListRequest(limit=2, cursor=page2.next_cursor)
        )
        assert len(page3.executions) == 1
        assert page3.next_cursor is None

        # Verify no overlap
        all_ids = [e.id for e in page1.executions + page2.executions + page3.executions]
        assert len(all_ids) == len(set(all_ids))

    def test_list_executions_invalid_status_raises_error(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_executions raises error for invalid status filter."""
        service = ScheduleQueryServiceImpl(sqlite_session_factory)

        with pytest.raises(ScheduleServiceError) as exc_info:
            service.list_executions(ExecutionListRequest(status="invalid_status"))

        assert exc_info.value.code == "validation_error"

    def test_list_executions_combined_filters(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_executions supports combining multiple filters."""
        actor = _actor_context()
        base_time = datetime(2025, 1, 14, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="interval",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        interval_count=1, interval_unit="hour"
                    ),
                ),
                actor,
                now=base_time,
            )
            # Create executions with different statuses and times
            exec1 = create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=base_time,
                    status="queued",
                ),
                _execution_actor_context("trace-1"),
                now=base_time,
            )
            exec2 = create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=base_time + timedelta(hours=1),
                    status="queued",
                ),
                _execution_actor_context("trace-2"),
                now=base_time + timedelta(hours=1),
            )
            # Update exec2 to succeeded
            update_execution(
                session,
                exec2.id,
                ExecutionUpdateInput(status="succeeded"),
                _execution_actor_context("trace-2-update"),
            )
            session.commit()
            schedule_id = schedule.id

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.list_executions(
            ExecutionListRequest(
                schedule_id=schedule_id,
                status="succeeded",
                created_after=base_time,
                created_before=base_time + timedelta(hours=2),
            )
        )

        assert len(result.executions) == 1
        assert result.executions[0].status == "succeeded"


# ============================================================================
# Execution Audit Inspection Tests
# ============================================================================


class TestExecutionAuditGet:
    """Tests for get_execution_audit detail view."""

    def test_get_execution_audit_returns_complete_view(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure get_execution_audit returns complete audit log view."""
        actor = _actor_context()
        exec_actor = _execution_actor_context()
        now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="one_time",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(run_at=now),
                ),
                actor,
                now=now - timedelta(hours=1),
            )
            execution = create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=now,
                    status="queued",
                ),
                exec_actor,
            )
            session.commit()

            # Get the audit log id
            from models import ExecutionAuditLog

            audit = (
                session.query(ExecutionAuditLog)
                .filter_by(execution_id=execution.id)
                .first()
            )
            audit_id = audit.id
            execution_id = execution.id
            schedule_id = schedule.id

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.get_execution_audit(
            ExecutionAuditGetRequest(execution_audit_id=audit_id)
        )

        assert result.audit_log.id == audit_id
        assert result.audit_log.execution_id == execution_id
        assert result.audit_log.schedule_id == schedule_id
        assert result.audit_log.status == "queued"
        assert result.audit_log.trace_id == "trace-exec-001"

    def test_get_execution_audit_not_found_raises_error(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure get_execution_audit raises ScheduleNotFoundError for missing audit."""
        service = ScheduleQueryServiceImpl(sqlite_session_factory)

        with pytest.raises(ScheduleNotFoundError) as exc_info:
            service.get_execution_audit(
                ExecutionAuditGetRequest(execution_audit_id=99999)
            )

        assert exc_info.value.code == "not_found"


# ============================================================================
# Audit Linkage Visibility Tests
# ============================================================================


class TestAuditLinkageVisibility:
    """Tests to ensure audit linkage fields are visible in responses."""

    def test_schedule_view_includes_last_run_info(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure ScheduleView includes last_run_at and last_run_status."""
        actor = _actor_context()
        now = datetime(2025, 1, 16, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="interval",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        interval_count=1, interval_unit="day"
                    ),
                ),
                actor,
                now=now,
            )
            # Simulate a completed execution by updating schedule
            schedule.last_run_at = now + timedelta(hours=1)
            schedule.last_run_status = "succeeded"
            session.commit()
            schedule_id = schedule.id

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.get_schedule(ScheduleGetRequest(schedule_id=schedule_id))

        # Compare without timezone as SQLite doesn't preserve it
        expected_last_run = (now + timedelta(hours=1)).replace(tzinfo=None)
        assert result.schedule.last_run_at.replace(tzinfo=None) == expected_last_run
        assert result.schedule.last_run_status == "succeeded"

    def test_schedule_view_includes_evaluation_fields_for_conditional(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure ScheduleView includes predicate evaluation fields for conditional schedules."""
        actor = _actor_context()
        now = datetime(2025, 1, 17, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Conditional task"), actor
            )
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="conditional",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        predicate_subject="skill.status",
                        predicate_operator="eq",
                        predicate_value="ready",
                        evaluation_interval_count=1,
                        evaluation_interval_unit="hour",
                    ),
                ),
                actor,
                now=now,
            )
            # Simulate an evaluation
            schedule.last_evaluated_at = now + timedelta(hours=1)
            schedule.last_evaluation_status = "true"
            session.commit()
            schedule_id = schedule.id

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.get_schedule(ScheduleGetRequest(schedule_id=schedule_id))

        assert result.schedule.schedule_type == "conditional"
        assert result.schedule.definition.predicate_subject == "skill.status"
        assert result.schedule.definition.predicate_operator == "eq"
        assert result.schedule.definition.predicate_value == "ready"
        assert result.schedule.definition.evaluation_interval_count == 1
        assert result.schedule.definition.evaluation_interval_unit == "hour"
        # Compare without timezone as SQLite doesn't preserve it
        expected_eval_at = (now + timedelta(hours=1)).replace(tzinfo=None)
        assert result.schedule.last_evaluated_at.replace(tzinfo=None) == expected_eval_at
        assert result.schedule.last_evaluation_status == "true"

    def test_execution_view_includes_audit_linkage_fields(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure ExecutionView includes audit-relevant fields."""
        actor = _actor_context()
        exec_actor = _execution_actor_context()
        now = datetime(2025, 1, 18, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="one_time",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(run_at=now),
                ),
                actor,
                now=now - timedelta(hours=1),
            )
            execution = create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=now,
                    status="queued",
                    max_attempts=5,
                ),
                exec_actor,
            )
            session.commit()
            execution_id = execution.id

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.get_execution(ExecutionGetRequest(execution_id=execution_id))

        # Audit linkage fields
        assert result.execution.actor_type == "scheduled"
        assert result.execution.trace_id == "trace-exec-001"
        assert result.execution.attempt_number == 0  # default for newly created execution
        assert result.execution.max_attempts == 5


# ============================================================================
# Ordering Tests
# ============================================================================


class TestOrdering:
    """Tests to verify consistent ordering (id descending)."""

    def test_list_schedules_ordered_by_id_desc(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_schedules returns schedules ordered by id descending."""
        actor = _actor_context()
        now = datetime(2025, 1, 19, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            ids = []
            for i in range(3):
                schedule = create_schedule(
                    session,
                    ScheduleCreateInput(
                        task_intent_id=intent.id,
                        schedule_type="one_time",
                        timezone="UTC",
                        definition=ScheduleDefinitionInput(
                            run_at=now + timedelta(hours=i + 1)
                        ),
                    ),
                    actor,
                    now=now,
                )
                ids.append(schedule.id)
            session.commit()

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.list_schedules(ScheduleListRequest())

        # Verify descending order
        assert result.schedules[0].id > result.schedules[1].id > result.schedules[2].id

    def test_list_executions_ordered_by_id_desc(
        self, sqlite_session_factory: sessionmaker
    ) -> None:
        """Ensure list_executions returns executions ordered by id descending."""
        actor = _actor_context()
        now = datetime(2025, 1, 20, 10, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent = create_task_intent(
                session, TaskIntentInput(summary="Test task"), actor
            )
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="interval",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        interval_count=1, interval_unit="hour"
                    ),
                ),
                actor,
                now=now,
            )
            ids = []
            for i in range(3):
                execution = create_execution(
                    session,
                    ExecutionCreateInput(
                        task_intent_id=intent.id,
                        schedule_id=schedule.id,
                        scheduled_for=now + timedelta(hours=i),
                        status="queued",
                    ),
                    _execution_actor_context(f"trace-{i}"),
                )
                ids.append(execution.id)
            session.commit()

        service = ScheduleQueryServiceImpl(sqlite_session_factory)
        result = service.list_executions(ExecutionListRequest())

        # Verify descending order
        assert result.executions[0].id > result.executions[1].id > result.executions[2].id
