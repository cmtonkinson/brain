"""Recording scheduler adapter stub for integration and audit tests."""

from __future__ import annotations

from datetime import datetime

from scheduler.adapter_interface import AdapterHealth, SchedulePayload, SchedulerAdapter


class RecordingSchedulerAdapter(SchedulerAdapter):
    """Simple adapter stub that records every scheduler call for assertions."""

    def __init__(self) -> None:
        """Initialize empty call tracking lists."""
        self.registered: list[SchedulePayload] = []
        self.updated: list[SchedulePayload] = []
        self.paused: list[int] = []
        self.resumed: list[int] = []
        self.deleted: list[int] = []
        self.triggered: list[tuple[int, datetime, str | None]] = []

    def register_schedule(self, payload: SchedulePayload) -> None:
        """Record schedule registration payloads."""
        self.registered.append(payload)

    def update_schedule(self, payload: SchedulePayload) -> None:
        """Record schedule update payloads."""
        self.updated.append(payload)

    def pause_schedule(self, schedule_id: int) -> None:
        """Record schedule pause events."""
        self.paused.append(schedule_id)

    def resume_schedule(self, schedule_id: int) -> None:
        """Record schedule resume events."""
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
        """Record run-now callback activity."""
        self.triggered.append((schedule_id, scheduled_for, trace_id))

    def check_health(self) -> AdapterHealth:
        """Stub health check returning OK."""
        return AdapterHealth(status="ok", message="stub adapter ready")
