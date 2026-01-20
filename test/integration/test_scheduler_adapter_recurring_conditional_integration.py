"""Integration tests for calendar-rule and conditional schedule adapter mapping.

This module tests the full flow of calendar-rule and conditional schedules through
the schedule command service to the adapter, verifying that:
- Calendar-rule schedules register correctly with Celery-compatible recurrence
- Conditional schedules register evaluation cadence callbacks
- Updates/pauses/deletes propagate correctly for these schedule types
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from models import Schedule, ScheduleAuditLog
from scheduler.adapter_interface import (
    AdapterHealth,
    ScheduleDefinition,
    SchedulePayload,
    SchedulerAdapter,
)
from scheduler.schedule_service import ScheduleCommandServiceImpl
from scheduler.schedule_service_interface import (
    ActorContext,
    ScheduleCreateRequest,
    ScheduleDeleteRequest,
    SchedulePauseRequest,
    ScheduleResumeRequest,
    ScheduleUpdateRequest,
    ScheduleDefinitionInput,
    TaskIntentInput,
)


def _actor_context() -> ActorContext:
    """Return a default actor context for schedule mutations."""
    return ActorContext(
        actor_type="human",
        actor_id="user-1",
        channel="signal",
        trace_id="trace-recur",
        request_id="req-recur",
        reason="integration-test",
    )


class RecordingAdapterStub(SchedulerAdapter):
    """Scheduler adapter stub that records all calls for verification."""

    def __init__(self) -> None:
        """Initialize recording storage."""
        self.registered: list[SchedulePayload] = []
        self.updated: list[SchedulePayload] = []
        self.paused: list[int] = []
        self.resumed: list[int] = []
        self.deleted: list[int] = []
        self.triggered: list[tuple[int, datetime, str | None]] = []

    def register_schedule(self, payload: SchedulePayload) -> None:
        """Record schedule registration."""
        self.registered.append(payload)

    def update_schedule(self, payload: SchedulePayload) -> None:
        """Record schedule update."""
        self.updated.append(payload)

    def pause_schedule(self, schedule_id: int) -> None:
        """Record schedule pause."""
        self.paused.append(schedule_id)

    def resume_schedule(self, schedule_id: int) -> None:
        """Record schedule resume."""
        self.resumed.append(schedule_id)

    def delete_schedule(self, schedule_id: int) -> None:
        """Record schedule deletion."""
        self.deleted.append(schedule_id)

    def trigger_callback(
        self,
        schedule_id: int,
        scheduled_for: datetime,
        *,
        trace_id: str | None = None,
    ) -> None:
        """Record run-now callback trigger."""
        self.triggered.append((schedule_id, scheduled_for, trace_id))

    def check_health(self) -> AdapterHealth:
        """Return a healthy status."""
        return AdapterHealth(status="ok", message="stub adapter ready")


# -----------------------------------------------------------------------------
# Calendar-rule schedule integration tests
# -----------------------------------------------------------------------------


def test_calendar_rule_schedule_creates_with_rrule_propagated_to_adapter(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure calendar-rule schedules register with RRULE in adapter payload."""
    now = datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc)
    adapter = RecordingAdapterStub()
    service = ScheduleCommandServiceImpl(
        sqlite_session_factory, adapter, now_provider=lambda: now
    )
    actor = _actor_context()

    result = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(
                summary="Weekly team sync",
                details="Runs every Monday at 9am.",
            ),
            schedule_type="calendar_rule",
            timezone="America/New_York",
            definition=ScheduleDefinitionInput(rrule="FREQ=WEEKLY;BYDAY=MO;BYHOUR=9"),
        ),
        actor,
    )

    # Verify the schedule was created
    assert result.schedule.schedule_type == "calendar_rule"
    assert result.schedule.definition.rrule == "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9"

    # Verify adapter received the correct payload
    assert len(adapter.registered) == 1
    payload = adapter.registered[0]
    assert payload.schedule_id == result.schedule.id
    assert payload.schedule_type == "calendar_rule"
    assert payload.timezone == "America/New_York"
    assert payload.definition.rrule == "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9"

    # Verify database state
    with closing(sqlite_session_factory()) as session:
        stored = session.query(Schedule).filter_by(id=result.schedule.id).one()
        assert stored.schedule_type == "calendar_rule"
        assert stored.rrule == "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9"
        assert stored.timezone == "America/New_York"


def test_calendar_rule_schedule_update_propagates_to_adapter(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure calendar-rule schedule updates propagate to the adapter."""
    now = datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc)
    adapter = RecordingAdapterStub()
    service = ScheduleCommandServiceImpl(
        sqlite_session_factory, adapter, now_provider=lambda: now
    )
    actor = _actor_context()

    # Create the schedule
    create_result = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(summary="Daily briefing"),
            schedule_type="calendar_rule",
            timezone="UTC",
            definition=ScheduleDefinitionInput(rrule="FREQ=DAILY;BYHOUR=8"),
        ),
        actor,
    )

    # Update to a different schedule
    update_result = service.update_schedule(
        ScheduleUpdateRequest(
            schedule_id=create_result.schedule.id,
            definition=ScheduleDefinitionInput(rrule="FREQ=DAILY;BYHOUR=9;BYMINUTE=30"),
        ),
        actor,
    )

    # Verify the update
    assert update_result.schedule.definition.rrule == "FREQ=DAILY;BYHOUR=9;BYMINUTE=30"

    # Verify adapter received the update
    assert len(adapter.updated) == 1
    payload = adapter.updated[0]
    assert payload.schedule_id == create_result.schedule.id
    assert payload.definition.rrule == "FREQ=DAILY;BYHOUR=9;BYMINUTE=30"


def test_calendar_rule_schedule_pause_resume_delete_flow(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure pause/resume/delete work correctly for calendar-rule schedules."""
    now = datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc)
    adapter = RecordingAdapterStub()
    service = ScheduleCommandServiceImpl(
        sqlite_session_factory, adapter, now_provider=lambda: now
    )
    actor = _actor_context()

    # Create the schedule
    create_result = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(summary="Monthly report"),
            schedule_type="calendar_rule",
            timezone="UTC",
            definition=ScheduleDefinitionInput(rrule="FREQ=MONTHLY;BYMONTHDAY=1"),
        ),
        actor,
    )
    schedule_id = create_result.schedule.id

    # Pause
    pause_result = service.pause_schedule(
        SchedulePauseRequest(schedule_id=schedule_id, reason="Temporarily disabled"),
        actor,
    )
    assert pause_result.schedule.state == "paused"

    # Resume
    resume_result = service.resume_schedule(
        ScheduleResumeRequest(schedule_id=schedule_id, reason="Re-enabled"),
        actor,
    )
    assert resume_result.schedule.state == "active"

    # Delete
    delete_result = service.delete_schedule(
        ScheduleDeleteRequest(schedule_id=schedule_id, reason="No longer needed"),
        actor,
    )
    assert delete_result.state == "canceled"

    # Verify adapter calls
    assert schedule_id in adapter.paused
    assert schedule_id in adapter.resumed
    assert schedule_id in adapter.deleted

    # Verify audit trail
    with closing(sqlite_session_factory()) as session:
        audits = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=schedule_id)
            .order_by(ScheduleAuditLog.id.asc())
            .all()
        )
    event_types = [a.event_type for a in audits]
    assert "create" in event_types
    assert "pause" in event_types
    assert "resume" in event_types
    assert "delete" in event_types


def test_calendar_rule_with_complex_rrule(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure complex RRULE patterns are preserved through the system."""
    now = datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc)
    adapter = RecordingAdapterStub()
    service = ScheduleCommandServiceImpl(
        sqlite_session_factory, adapter, now_provider=lambda: now
    )
    actor = _actor_context()

    # Complex: every 2 hours on weekdays
    rrule = "FREQ=HOURLY;INTERVAL=2;BYDAY=MO,TU,WE,TH,FR;BYHOUR=9,11,13,15,17"

    result = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(summary="Business hours check"),
            schedule_type="calendar_rule",
            timezone="Europe/London",
            definition=ScheduleDefinitionInput(rrule=rrule),
        ),
        actor,
    )

    assert result.schedule.definition.rrule == rrule
    assert adapter.registered[0].definition.rrule == rrule


# -----------------------------------------------------------------------------
# Conditional schedule integration tests
# -----------------------------------------------------------------------------


def test_conditional_schedule_creates_with_evaluation_cadence(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure conditional schedules register with evaluation interval in adapter."""
    now = datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc)
    adapter = RecordingAdapterStub()
    service = ScheduleCommandServiceImpl(
        sqlite_session_factory, adapter, now_provider=lambda: now
    )
    actor = _actor_context()

    result = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(
                summary="Check memory hygiene",
                details="Trigger when memory score drops below threshold.",
            ),
            schedule_type="conditional",
            timezone="UTC",
            definition=ScheduleDefinitionInput(
                predicate_subject="memory.hygiene.score",
                predicate_operator="lt",
                predicate_value="80",
                evaluation_interval_count=6,
                evaluation_interval_unit="hour",
            ),
        ),
        actor,
    )

    # Verify the schedule was created
    assert result.schedule.schedule_type == "conditional"
    assert result.schedule.definition.predicate_subject == "memory.hygiene.score"
    assert result.schedule.definition.predicate_operator == "lt"
    assert result.schedule.definition.predicate_value == "80"
    assert result.schedule.definition.evaluation_interval_count == 6
    assert result.schedule.definition.evaluation_interval_unit == "hour"

    # Verify adapter received the correct payload
    assert len(adapter.registered) == 1
    payload = adapter.registered[0]
    assert payload.schedule_id == result.schedule.id
    assert payload.schedule_type == "conditional"
    assert payload.definition.predicate_subject == "memory.hygiene.score"
    assert payload.definition.evaluation_interval_count == 6
    assert payload.definition.evaluation_interval_unit == "hour"

    # Verify database state
    with closing(sqlite_session_factory()) as session:
        stored = session.query(Schedule).filter_by(id=result.schedule.id).one()
        assert stored.schedule_type == "conditional"
        assert stored.predicate_subject == "memory.hygiene.score"
        assert stored.predicate_operator == "lt"
        assert stored.predicate_value == "80"
        assert stored.evaluation_interval_count == 6
        assert stored.evaluation_interval_unit == "hour"


def test_conditional_schedule_update_propagates_to_adapter(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure conditional schedule updates propagate to the adapter."""
    now = datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc)
    adapter = RecordingAdapterStub()
    service = ScheduleCommandServiceImpl(
        sqlite_session_factory, adapter, now_provider=lambda: now
    )
    actor = _actor_context()

    # Create the schedule
    create_result = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(summary="API health check"),
            schedule_type="conditional",
            timezone="UTC",
            definition=ScheduleDefinitionInput(
                predicate_subject="api.status",
                predicate_operator="neq",
                predicate_value="healthy",
                evaluation_interval_count=5,
                evaluation_interval_unit="minute",
            ),
        ),
        actor,
    )

    # Update evaluation cadence
    update_result = service.update_schedule(
        ScheduleUpdateRequest(
            schedule_id=create_result.schedule.id,
            definition=ScheduleDefinitionInput(
                predicate_subject="api.status",
                predicate_operator="neq",
                predicate_value="healthy",
                evaluation_interval_count=15,
                evaluation_interval_unit="minute",
            ),
        ),
        actor,
    )

    # Verify the update
    assert update_result.schedule.definition.evaluation_interval_count == 15

    # Verify adapter received the update
    assert len(adapter.updated) == 1
    payload = adapter.updated[0]
    assert payload.schedule_id == create_result.schedule.id
    assert payload.definition.evaluation_interval_count == 15


def test_conditional_schedule_pause_resume_delete_flow(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure pause/resume/delete work correctly for conditional schedules."""
    now = datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc)
    adapter = RecordingAdapterStub()
    service = ScheduleCommandServiceImpl(
        sqlite_session_factory, adapter, now_provider=lambda: now
    )
    actor = _actor_context()

    # Create the schedule
    create_result = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(summary="Backup monitor"),
            schedule_type="conditional",
            timezone="UTC",
            definition=ScheduleDefinitionInput(
                predicate_subject="backup.status",
                predicate_operator="exists",
                evaluation_interval_count=1,
                evaluation_interval_unit="day",
            ),
        ),
        actor,
    )
    schedule_id = create_result.schedule.id

    # Pause
    pause_result = service.pause_schedule(
        SchedulePauseRequest(schedule_id=schedule_id, reason="Maintenance"),
        actor,
    )
    assert pause_result.schedule.state == "paused"

    # Resume
    resume_result = service.resume_schedule(
        ScheduleResumeRequest(schedule_id=schedule_id, reason="Maintenance complete"),
        actor,
    )
    assert resume_result.schedule.state == "active"

    # Delete
    delete_result = service.delete_schedule(
        ScheduleDeleteRequest(schedule_id=schedule_id, reason="Deprecated"),
        actor,
    )
    assert delete_result.state == "canceled"

    # Verify adapter calls
    assert schedule_id in adapter.paused
    assert schedule_id in adapter.resumed
    assert schedule_id in adapter.deleted


def test_conditional_schedule_with_numeric_predicate_value(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure conditional schedules handle numeric predicate values correctly."""
    now = datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc)
    adapter = RecordingAdapterStub()
    service = ScheduleCommandServiceImpl(
        sqlite_session_factory, adapter, now_provider=lambda: now
    )
    actor = _actor_context()

    result = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(summary="High CPU alert"),
            schedule_type="conditional",
            timezone="UTC",
            definition=ScheduleDefinitionInput(
                predicate_subject="system.cpu.usage",
                predicate_operator="gt",
                predicate_value="90",
                evaluation_interval_count=1,
                evaluation_interval_unit="minute",
            ),
        ),
        actor,
    )

    assert result.schedule.definition.predicate_value == "90"
    assert adapter.registered[0].definition.predicate_value == "90"


def test_conditional_schedule_with_exists_operator(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure conditional schedules with 'exists' operator work without predicate_value."""
    now = datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc)
    adapter = RecordingAdapterStub()
    service = ScheduleCommandServiceImpl(
        sqlite_session_factory, adapter, now_provider=lambda: now
    )
    actor = _actor_context()

    result = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(summary="File existence check"),
            schedule_type="conditional",
            timezone="UTC",
            definition=ScheduleDefinitionInput(
                predicate_subject="file.important.txt",
                predicate_operator="exists",
                evaluation_interval_count=1,
                evaluation_interval_unit="week",
            ),
        ),
        actor,
    )

    assert result.schedule.definition.predicate_operator == "exists"
    assert result.schedule.definition.evaluation_interval_unit == "week"
    assert adapter.registered[0].definition.predicate_operator == "exists"
