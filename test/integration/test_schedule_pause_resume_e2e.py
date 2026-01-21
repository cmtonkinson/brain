"""End-to-end integration tests for pause/resume schedule transitions."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from models import Schedule, ScheduleAuditLog
from scheduler.adapter_interface import AdapterHealth, SchedulePayload, SchedulerAdapter
from scheduler.schedule_service import ScheduleCommandServiceImpl
from scheduler.schedule_service_interface import (
    ActorContext,
    ScheduleConflictError,
    ScheduleCreateRequest,
    ScheduleDefinitionInput,
    SchedulePauseRequest,
    ScheduleResumeRequest,
    TaskIntentInput,
)


def _actor_context() -> ActorContext:
    """Return a default API actor context used by the command flow."""
    return ActorContext(
        actor_type="human",
        actor_id="pause-resume-test",
        channel="signal",
        trace_id="trace-pause-resume",
        request_id="req-pause-resume",
        reason="integration-test",
    )


class _RecordingAdapter(SchedulerAdapter):
    """Stub adapter that records pause/resume calls for verification."""

    def __init__(self) -> None:
        """Initialize storage for adapter interactions."""
        self.registered: list[SchedulePayload] = []
        self.updated: list[SchedulePayload] = []
        self.paused: list[int] = []
        self.resumed: list[int] = []
        self.deleted: list[int] = []
        self.triggered: list[tuple[int, datetime, str | None]] = []

    def register_schedule(self, payload: SchedulePayload) -> None:
        """Record schedule registrations."""
        self.registered.append(payload)

    def update_schedule(self, payload: SchedulePayload) -> None:
        """Record schedule updates."""
        self.updated.append(payload)

    def pause_schedule(self, schedule_id: int) -> None:
        """Record schedule pauses."""
        self.paused.append(schedule_id)

    def resume_schedule(self, schedule_id: int) -> None:
        """Record schedule resumes."""
        self.resumed.append(schedule_id)

    def delete_schedule(self, schedule_id: int) -> None:
        """Record schedule deletions."""
        self.deleted.append(schedule_id)

    def trigger_callback(
        self,
        schedule_id: int,
        scheduled_for: datetime,
        *,
        trace_id: str | None = None,
    ) -> None:
        """Record adapter callback triggers."""
        self.triggered.append((schedule_id, scheduled_for, trace_id))

    def check_health(self) -> AdapterHealth:
        """Return a healthy status for the stub."""
        return AdapterHealth(status="ok", message="stub adapter ready")


def _build_service(
    sqlite_session_factory: sessionmaker,
    now: datetime,
) -> tuple[_RecordingAdapter, ScheduleCommandServiceImpl, ActorContext]:
    """Construct the schedule service stack with a deterministic clock."""
    adapter = _RecordingAdapter()
    service = ScheduleCommandServiceImpl(
        sqlite_session_factory,
        adapter,
        now_provider=lambda: now,
    )
    return adapter, service, _actor_context()


def _create_interval_schedule(service: ScheduleCommandServiceImpl, actor: ActorContext):
    """Create a simple interval schedule for the tests."""
    return service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(
                summary="Pause/resume validation",
                details="Ensure state transitions behave as expected.",
            ),
            schedule_type="interval",
            timezone="UTC",
            definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        actor,
    )


def test_pause_resume_records_state_and_audit(sqlite_session_factory: sessionmaker) -> None:
    """Ensure pause/resume transitions are audited and the state tracks correctly."""
    now = datetime(2025, 1, 2, 7, 0, tzinfo=timezone.utc)
    adapter, service, actor = _build_service(sqlite_session_factory, now)

    create_result = _create_interval_schedule(service, actor)
    schedule_id = create_result.schedule.id

    pause_reason = "maintenance window"
    pause_result = service.pause_schedule(
        SchedulePauseRequest(schedule_id=schedule_id, reason=pause_reason),
        actor,
    )
    assert pause_result.schedule.state == "paused"
    assert pause_result.audit_log_id is not None

    resume_reason = "maintenance complete"
    resume_result = service.resume_schedule(
        ScheduleResumeRequest(schedule_id=schedule_id, reason=resume_reason),
        actor,
    )
    assert resume_result.schedule.state == "active"
    assert resume_result.audit_log_id is not None

    with closing(sqlite_session_factory()) as session:
        stored_schedule = session.query(Schedule).filter_by(id=schedule_id).one()
        audits = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=schedule_id)
            .order_by(ScheduleAuditLog.id.asc())
            .all()
        )

    pause_audits = [log for log in audits if log.event_type == "pause"]
    resume_audits = [log for log in audits if log.event_type == "resume"]

    assert stored_schedule.state == "active"
    assert len(pause_audits) == 1
    assert len(resume_audits) == 1
    assert pause_result.audit_log_id == pause_audits[0].id
    assert resume_result.audit_log_id == resume_audits[0].id
    assert pause_audits[0].reason == pause_reason
    assert resume_audits[0].reason == resume_reason
    assert schedule_id in adapter.paused
    assert schedule_id in adapter.resumed


def test_pause_resume_conflicts_reject_redundant_state_changes(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Verify that repeated pause/resume attempts raise conflicts and do not write duplicate audits."""
    now = datetime(2025, 1, 2, 8, 0, tzinfo=timezone.utc)
    adapter, service, actor = _build_service(sqlite_session_factory, now)

    create_result = _create_interval_schedule(service, actor)
    schedule_id = create_result.schedule.id

    service.pause_schedule(
        SchedulePauseRequest(schedule_id=schedule_id, reason="initial pause"),
        actor,
    )

    with pytest.raises(ScheduleConflictError) as pause_conflict:
        service.pause_schedule(
            SchedulePauseRequest(schedule_id=schedule_id, reason="duplicate pause"),
            actor,
        )
    assert pause_conflict.value.details == {"current_state": "paused", "target_state": "paused"}

    service.resume_schedule(
        ScheduleResumeRequest(schedule_id=schedule_id, reason="initial resume"),
        actor,
    )
    with pytest.raises(ScheduleConflictError) as resume_conflict:
        service.resume_schedule(
            ScheduleResumeRequest(schedule_id=schedule_id, reason="duplicate resume"),
            actor,
        )
    assert resume_conflict.value.details == {"current_state": "active", "target_state": "active"}

    assert adapter.paused.count(schedule_id) == 1
    assert adapter.resumed.count(schedule_id) == 1

    with closing(sqlite_session_factory()) as session:
        pause_audit_entries = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=schedule_id, event_type="pause")
            .all()
        )
        resume_audit_entries = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=schedule_id, event_type="resume")
            .all()
        )

    assert len(pause_audit_entries) == 1
    assert len(resume_audit_entries) == 1
