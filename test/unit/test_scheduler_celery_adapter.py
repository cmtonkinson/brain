"""Unit tests for the Celery scheduler adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from scheduler.adapter_interface import ScheduleDefinition, SchedulePayload, SchedulerAdapterError
from scheduler.adapters.celery_adapter import (
    CeleryAdapterConfig,
    CeleryEtaSchedule,
    CeleryIntervalSchedule,
    CelerySchedulerAdapter,
)


@dataclass
class _EnqueueCall:
    """Captured enqueue call information for adapter tests."""

    schedule_id: int
    scheduled_for: datetime
    eta: datetime
    queue_name: str | None


class _FakeCeleryClient:
    """In-memory Celery client capturing adapter operations."""

    def __init__(self) -> None:
        """Initialize the fake client call history."""
        self.registered = []
        self.updated = []
        self.paused: list[str] = []
        self.resumed: list[str] = []
        self.deleted: list[str] = []
        self.enqueued: list[_EnqueueCall] = []
        self.health_ok = True

    def register_entry(self, entry) -> None:
        """Capture a registered entry."""
        self.registered.append(entry)

    def update_entry(self, entry) -> None:
        """Capture an updated entry."""
        self.updated.append(entry)

    def pause_entry(self, entry_name: str) -> None:
        """Capture a pause call."""
        self.paused.append(entry_name)

    def resume_entry(self, entry_name: str) -> None:
        """Capture a resume call."""
        self.resumed.append(entry_name)

    def delete_entry(self, entry_name: str) -> None:
        """Capture a delete call."""
        self.deleted.append(entry_name)

    def enqueue_callback(self, payload, *, eta: datetime, queue_name: str | None) -> None:
        """Capture an enqueue call."""
        self.enqueued.append(
            _EnqueueCall(
                schedule_id=payload.schedule_id,
                scheduled_for=payload.scheduled_for,
                eta=eta,
                queue_name=queue_name,
            )
        )

    def check_health(self) -> bool:
        """Return the configured health status."""
        return self.health_ok


def _adapter(client: _FakeCeleryClient) -> CelerySchedulerAdapter:
    """Build a Celery scheduler adapter for tests."""
    config = CeleryAdapterConfig(callback_task_name="scheduler.dispatch", queue_name="scheduler")
    return CelerySchedulerAdapter(client, config)


def _run_at() -> datetime:
    """Return a timezone-aware run-at time for tests."""
    return datetime(2025, 1, 2, 9, 30, tzinfo=timezone.utc)


def test_register_one_time_schedule_builds_eta_entry() -> None:
    """Ensure one-time schedules translate into ETA-based entries."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    payload = SchedulePayload(
        schedule_id=101,
        schedule_type="one_time",
        timezone="UTC",
        definition=ScheduleDefinition(run_at=_run_at()),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert entry.name == "schedule:101"
    assert isinstance(entry.schedule, CeleryEtaSchedule)
    assert entry.schedule.eta == _run_at()
    assert entry.kwargs["schedule_id"] == 101
    assert entry.kwargs["scheduled_for"] == _run_at()


def test_register_interval_schedule_builds_interval_entry() -> None:
    """Ensure interval schedules translate into Celery interval entries."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    anchor_at = datetime(2025, 1, 2, 9, 0, tzinfo=timezone.utc)
    payload = SchedulePayload(
        schedule_id=202,
        schedule_type="interval",
        timezone="UTC",
        definition=ScheduleDefinition(
            interval_count=5,
            interval_unit="minute",
            anchor_at=anchor_at,
        ),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert entry.name == "schedule:202"
    assert isinstance(entry.schedule, CeleryIntervalSchedule)
    assert entry.schedule.every == 5
    assert entry.schedule.period == "minutes"
    assert entry.schedule.anchor_at == anchor_at
    assert entry.kwargs["schedule_id"] == 202
    assert entry.kwargs["scheduled_for"] is None


def test_register_interval_month_is_rejected() -> None:
    """Ensure unsupported interval units raise a structured adapter error."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    payload = SchedulePayload(
        schedule_id=303,
        schedule_type="interval",
        timezone="UTC",
        definition=ScheduleDefinition(interval_count=1, interval_unit="month"),
    )

    with pytest.raises(SchedulerAdapterError) as exc:
        adapter.register_schedule(payload)

    assert exc.value.code == "unsupported_interval_unit"


def test_register_unsupported_schedule_type_is_rejected() -> None:
    """Ensure unsupported schedule types are rejected by the adapter."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    payload = SchedulePayload(
        schedule_id=404,
        schedule_type="calendar_rule",
        timezone="UTC",
        definition=ScheduleDefinition(rrule="FREQ=DAILY"),
    )

    with pytest.raises(SchedulerAdapterError) as exc:
        adapter.register_schedule(payload)

    assert exc.value.code == "unsupported_schedule_type"


def test_trigger_callback_enqueues_immediate_task() -> None:
    """Ensure run-now translates into an immediate callback enqueue."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    scheduled_for = datetime(2025, 2, 1, 12, 0, tzinfo=timezone.utc)

    adapter.trigger_callback(505, scheduled_for)

    assert client.enqueued
    call = client.enqueued[-1]
    assert call.schedule_id == 505
    assert call.scheduled_for == scheduled_for
    assert call.eta == scheduled_for
    assert call.queue_name == "scheduler"


def test_pause_resume_delete_calls_provider() -> None:
    """Ensure pause/resume/delete delegate to the provider client."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)

    adapter.pause_schedule(606)
    adapter.resume_schedule(606)
    adapter.delete_schedule(606)

    assert client.paused == ["schedule:606"]
    assert client.resumed == ["schedule:606"]
    assert client.deleted == ["schedule:606"]


def test_check_health_reports_status() -> None:
    """Ensure adapter health reflects provider status."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)

    client.health_ok = True
    health = adapter.check_health()
    assert health.status == "ok"

    client.health_ok = False
    health = adapter.check_health()
    assert health.status == "unhealthy"
