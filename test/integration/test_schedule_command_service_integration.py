"""Integration tests for the schedule command service."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from models import Schedule, ScheduleAuditLog
from scheduler.adapter_interface import AdapterHealth, SchedulePayload, SchedulerAdapter
from scheduler.schedule_service import ScheduleCommandServiceImpl
from scheduler.schedule_service_interface import (
    ActorContext,
    ScheduleCreateRequest,
    ScheduleDeleteRequest,
    ScheduleUpdateRequest,
    ScheduleRunNowRequest,
    ScheduleDefinitionInput,
    TaskIntentInput,
)


def _actor_context() -> ActorContext:
    """Return a default actor context for schedule mutations."""
    return ActorContext(
        actor_type="human",
        actor_id="user-1",
        channel="signal",
        trace_id="trace-abc",
        request_id="req-123",
        reason="integration-test",
    )


class AdapterStub(SchedulerAdapter):
    """In-memory scheduler adapter stub for integration tests."""

    def __init__(self) -> None:
        """Initialize stub call storage."""
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
        """Record run-now trigger callbacks."""
        self.triggered.append((schedule_id, scheduled_for, trace_id))

    def check_health(self) -> object:
        """Return a stub health indicator."""
        return AdapterHealth(status="ok", message="stub adapter ready")


def test_schedule_service_create_update_delete_happy_path(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure create/update/delete flows succeed through the command service."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    adapter = AdapterStub()
    service = ScheduleCommandServiceImpl(sqlite_session_factory, adapter, now_provider=lambda: now)
    actor = _actor_context()

    create_result = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(
                summary="Daily review",
                details="Review outstanding tasks.",
            ),
            schedule_type="interval",
            timezone="UTC",
            definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        actor,
    )

    update_result = service.update_schedule(
        ScheduleUpdateRequest(
            schedule_id=create_result.schedule.id,
            definition=ScheduleDefinitionInput(interval_count=2, interval_unit="day"),
        ),
        actor,
    )

    run_now_result = service.run_now(
        ScheduleRunNowRequest(schedule_id=create_result.schedule.id),
        actor,
    )

    delete_result = service.delete_schedule(
        ScheduleDeleteRequest(schedule_id=create_result.schedule.id),
        actor,
    )

    assert create_result.audit_log_id is not None
    assert update_result.audit_log_id is not None
    assert run_now_result.audit_log_id is not None
    assert delete_result.state == "canceled"

    with closing(sqlite_session_factory()) as session:
        stored = session.query(Schedule).filter_by(id=create_result.schedule.id).one()
        audits = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=create_result.schedule.id)
            .order_by(ScheduleAuditLog.id.asc())
            .all()
        )

    assert stored.state == "canceled"
    assert [audit.event_type for audit in audits] == ["create", "update", "run_now", "delete"]
    assert adapter.registered[0].schedule_id == create_result.schedule.id
    assert adapter.updated[0].schedule_id == create_result.schedule.id
    assert adapter.triggered[0][0] == create_result.schedule.id
    assert adapter.deleted[0] == create_result.schedule.id
