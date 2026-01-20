"""Unit tests for the Celery scheduler adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from scheduler.adapter_interface import ScheduleDefinition, SchedulePayload, SchedulerAdapterError
from scheduler.adapters.celery_adapter import (
    CeleryAdapterConfig,
    CeleryCrontabSchedule,
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
    trace_id: str | None


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
                trace_id=payload.trace_id,
            )
        )

    def check_health(self) -> bool:
        """Return the configured health status."""
        return self.health_ok


def _adapter(client: _FakeCeleryClient) -> CelerySchedulerAdapter:
    """Build a Celery scheduler adapter for tests."""
    config = CeleryAdapterConfig(callback_task_name="scheduler.dispatch", queue_name="scheduler")
    return CelerySchedulerAdapter(client, config)


def _adapter_with_evaluation_callback(client: _FakeCeleryClient) -> CelerySchedulerAdapter:
    """Build a Celery scheduler adapter with evaluation callback task for conditional schedules."""
    config = CeleryAdapterConfig(
        callback_task_name="scheduler.dispatch",
        evaluation_callback_task_name="scheduler.evaluate_predicate",
        queue_name="scheduler",
    )
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


def test_register_unknown_schedule_type_is_rejected() -> None:
    """Ensure unknown schedule types are rejected by the adapter."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    payload = SchedulePayload(
        schedule_id=404,
        schedule_type="unknown_type",
        timezone="UTC",
        definition=ScheduleDefinition(),
    )

    with pytest.raises(SchedulerAdapterError) as exc:
        adapter.register_schedule(payload)

    assert exc.value.code == "unsupported_schedule_type"


def test_trigger_callback_enqueues_immediate_task() -> None:
    """Ensure run-now translates into an immediate callback enqueue."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    scheduled_for = datetime(2025, 2, 1, 12, 0, tzinfo=timezone.utc)

    adapter.trigger_callback(505, scheduled_for, trace_id="trace-505")

    assert client.enqueued
    call = client.enqueued[-1]
    assert call.schedule_id == 505
    assert call.scheduled_for == scheduled_for
    assert call.eta == scheduled_for
    assert call.queue_name == "scheduler"
    assert call.trace_id == "trace-505"


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


# -----------------------------------------------------------------------------
# Calendar-rule schedule tests (RRULE to crontab mapping)
# -----------------------------------------------------------------------------


def test_register_calendar_rule_daily_builds_crontab_entry() -> None:
    """Ensure daily RRULE schedules translate into crontab entries."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    payload = SchedulePayload(
        schedule_id=501,
        schedule_type="calendar_rule",
        timezone="UTC",
        definition=ScheduleDefinition(rrule="FREQ=DAILY"),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert entry.name == "schedule:501"
    assert isinstance(entry.schedule, CeleryCrontabSchedule)
    # Daily at midnight by default
    assert entry.schedule.minute == "0"
    assert entry.schedule.hour == "0"
    assert entry.schedule.day_of_week == "*"
    assert entry.schedule.day_of_month == "*"
    assert entry.schedule.month_of_year == "*"


def test_register_calendar_rule_weekly_with_byday() -> None:
    """Ensure weekly RRULE with BYDAY maps to correct day_of_week."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    # Every Monday, Wednesday, Friday
    payload = SchedulePayload(
        schedule_id=502,
        schedule_type="calendar_rule",
        timezone="America/New_York",
        definition=ScheduleDefinition(rrule="FREQ=WEEKLY;BYDAY=MO,WE,FR"),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert isinstance(entry.schedule, CeleryCrontabSchedule)
    # MO=1, WE=3, FR=5 in crontab
    assert entry.schedule.day_of_week == "1,3,5"
    assert entry.schedule.minute == "0"
    assert entry.schedule.hour == "0"


def test_register_calendar_rule_with_byhour_byminute() -> None:
    """Ensure BYHOUR and BYMINUTE map to crontab hour and minute."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    payload = SchedulePayload(
        schedule_id=503,
        schedule_type="calendar_rule",
        timezone="UTC",
        definition=ScheduleDefinition(rrule="FREQ=DAILY;BYHOUR=9;BYMINUTE=30"),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert isinstance(entry.schedule, CeleryCrontabSchedule)
    assert entry.schedule.hour == "9"
    assert entry.schedule.minute == "30"


def test_register_calendar_rule_monthly_with_bymonthday() -> None:
    """Ensure monthly RRULE with BYMONTHDAY maps correctly."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    # 15th of every month
    payload = SchedulePayload(
        schedule_id=504,
        schedule_type="calendar_rule",
        timezone="UTC",
        definition=ScheduleDefinition(rrule="FREQ=MONTHLY;BYMONTHDAY=15"),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert isinstance(entry.schedule, CeleryCrontabSchedule)
    assert entry.schedule.day_of_month == "15"
    assert entry.schedule.minute == "0"
    assert entry.schedule.hour == "0"


def test_register_calendar_rule_yearly_with_bymonth() -> None:
    """Ensure yearly RRULE with BYMONTH maps correctly."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    # January 1st every year
    payload = SchedulePayload(
        schedule_id=505,
        schedule_type="calendar_rule",
        timezone="UTC",
        definition=ScheduleDefinition(rrule="FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=1"),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert isinstance(entry.schedule, CeleryCrontabSchedule)
    assert entry.schedule.month_of_year == "1"
    assert entry.schedule.day_of_month == "1"


def test_register_calendar_rule_hourly_with_interval() -> None:
    """Ensure hourly RRULE with INTERVAL maps to step expression."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    # Every 2 hours
    payload = SchedulePayload(
        schedule_id=506,
        schedule_type="calendar_rule",
        timezone="UTC",
        definition=ScheduleDefinition(rrule="FREQ=HOURLY;INTERVAL=2"),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert isinstance(entry.schedule, CeleryCrontabSchedule)
    assert entry.schedule.hour == "*/2"
    assert entry.schedule.minute == "0"


def test_register_calendar_rule_minutely() -> None:
    """Ensure minutely RRULE maps to crontab with minute wildcard."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    # Every 5 minutes
    payload = SchedulePayload(
        schedule_id=507,
        schedule_type="calendar_rule",
        timezone="UTC",
        definition=ScheduleDefinition(rrule="FREQ=MINUTELY;INTERVAL=5"),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert isinstance(entry.schedule, CeleryCrontabSchedule)
    assert entry.schedule.minute == "*/5"


def test_register_calendar_rule_missing_rrule_is_rejected() -> None:
    """Ensure calendar_rule without rrule is rejected."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    payload = SchedulePayload(
        schedule_id=508,
        schedule_type="calendar_rule",
        timezone="UTC",
        definition=ScheduleDefinition(),
    )

    with pytest.raises(SchedulerAdapterError) as exc:
        adapter.register_schedule(payload)

    # Validation layer catches this before adapter-specific logic
    assert exc.value.code == "invalid_schedule_definition"


def test_register_calendar_rule_missing_freq_is_rejected() -> None:
    """Ensure RRULE without FREQ is rejected."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    payload = SchedulePayload(
        schedule_id=509,
        schedule_type="calendar_rule",
        timezone="UTC",
        definition=ScheduleDefinition(rrule="BYDAY=MO"),
    )

    with pytest.raises(SchedulerAdapterError) as exc:
        adapter.register_schedule(payload)

    # Validation layer catches missing FREQ before adapter-specific logic
    assert exc.value.code == "invalid_schedule_definition"


def test_register_calendar_rule_unsupported_freq_is_rejected() -> None:
    """Ensure unsupported RRULE FREQ is rejected."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    payload = SchedulePayload(
        schedule_id=510,
        schedule_type="calendar_rule",
        timezone="UTC",
        definition=ScheduleDefinition(rrule="FREQ=SECONDLY"),
    )

    with pytest.raises(SchedulerAdapterError) as exc:
        adapter.register_schedule(payload)

    assert exc.value.code == "unsupported_rrule_freq"


def test_update_calendar_rule_schedule() -> None:
    """Ensure calendar_rule schedules can be updated via the adapter."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    payload = SchedulePayload(
        schedule_id=511,
        schedule_type="calendar_rule",
        timezone="UTC",
        definition=ScheduleDefinition(rrule="FREQ=WEEKLY;BYDAY=TU,TH"),
    )

    adapter.update_schedule(payload)

    entry = client.updated[-1]
    assert entry.name == "schedule:511"
    assert isinstance(entry.schedule, CeleryCrontabSchedule)
    assert entry.schedule.day_of_week == "2,4"  # TU=2, TH=4


# -----------------------------------------------------------------------------
# Conditional schedule tests (evaluation cadence mapping)
# -----------------------------------------------------------------------------


def test_register_conditional_schedule_builds_interval_for_evaluation() -> None:
    """Ensure conditional schedules build interval for evaluation cadence."""
    client = _FakeCeleryClient()
    adapter = _adapter_with_evaluation_callback(client)
    payload = SchedulePayload(
        schedule_id=601,
        schedule_type="conditional",
        timezone="UTC",
        definition=ScheduleDefinition(
            predicate_subject="obsidian.notes.count",
            predicate_operator="gt",
            predicate_value="100",
            evaluation_interval_count=15,
            evaluation_interval_unit="minute",
        ),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert entry.name == "schedule:601"
    assert entry.task == "scheduler.evaluate_predicate"
    assert isinstance(entry.schedule, CeleryIntervalSchedule)
    assert entry.schedule.every == 15
    assert entry.schedule.period == "minutes"
    assert entry.schedule.anchor_at is None


def test_register_conditional_schedule_with_hourly_cadence() -> None:
    """Ensure conditional schedules support hourly evaluation cadence."""
    client = _FakeCeleryClient()
    adapter = _adapter_with_evaluation_callback(client)
    payload = SchedulePayload(
        schedule_id=602,
        schedule_type="conditional",
        timezone="America/Los_Angeles",
        definition=ScheduleDefinition(
            predicate_subject="api.status",
            predicate_operator="eq",
            predicate_value="healthy",
            evaluation_interval_count=6,
            evaluation_interval_unit="hour",
        ),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert isinstance(entry.schedule, CeleryIntervalSchedule)
    assert entry.schedule.every == 6
    assert entry.schedule.period == "hours"


def test_register_conditional_schedule_with_daily_cadence() -> None:
    """Ensure conditional schedules support daily evaluation cadence."""
    client = _FakeCeleryClient()
    adapter = _adapter_with_evaluation_callback(client)
    payload = SchedulePayload(
        schedule_id=603,
        schedule_type="conditional",
        timezone="UTC",
        definition=ScheduleDefinition(
            predicate_subject="memory.hygiene.score",
            predicate_operator="lt",
            predicate_value="80",
            evaluation_interval_count=1,
            evaluation_interval_unit="day",
        ),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert isinstance(entry.schedule, CeleryIntervalSchedule)
    assert entry.schedule.every == 1
    assert entry.schedule.period == "days"


def test_register_conditional_schedule_with_weekly_cadence() -> None:
    """Ensure conditional schedules support weekly evaluation cadence."""
    client = _FakeCeleryClient()
    adapter = _adapter_with_evaluation_callback(client)
    payload = SchedulePayload(
        schedule_id=604,
        schedule_type="conditional",
        timezone="UTC",
        definition=ScheduleDefinition(
            predicate_subject="backup.last_run",
            predicate_operator="exists",
            predicate_value=None,
            evaluation_interval_count=1,
            evaluation_interval_unit="week",
        ),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert isinstance(entry.schedule, CeleryIntervalSchedule)
    assert entry.schedule.every == 1
    assert entry.schedule.period == "weeks"


def test_register_conditional_missing_evaluation_callback_task_is_rejected() -> None:
    """Ensure conditional schedules require evaluation_callback_task_name in config."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)  # No evaluation_callback_task_name
    payload = SchedulePayload(
        schedule_id=605,
        schedule_type="conditional",
        timezone="UTC",
        definition=ScheduleDefinition(
            predicate_subject="test.subject",
            predicate_operator="eq",
            predicate_value="value",
            evaluation_interval_count=10,
            evaluation_interval_unit="minute",
        ),
    )

    with pytest.raises(SchedulerAdapterError) as exc:
        adapter.register_schedule(payload)

    assert exc.value.code == "missing_evaluation_callback_task"


def test_register_conditional_missing_evaluation_interval_count_is_rejected() -> None:
    """Ensure conditional schedules require evaluation_interval_count."""
    client = _FakeCeleryClient()
    adapter = _adapter_with_evaluation_callback(client)
    payload = SchedulePayload(
        schedule_id=606,
        schedule_type="conditional",
        timezone="UTC",
        definition=ScheduleDefinition(
            predicate_subject="test.subject",
            predicate_operator="eq",
            predicate_value="value",
            evaluation_interval_unit="minute",
        ),
    )

    with pytest.raises(SchedulerAdapterError) as exc:
        adapter.register_schedule(payload)

    # Validation layer catches this before adapter-specific logic
    assert exc.value.code == "invalid_schedule_definition"


def test_register_conditional_missing_evaluation_interval_unit_is_rejected() -> None:
    """Ensure conditional schedules require evaluation_interval_unit."""
    client = _FakeCeleryClient()
    adapter = _adapter_with_evaluation_callback(client)
    payload = SchedulePayload(
        schedule_id=607,
        schedule_type="conditional",
        timezone="UTC",
        definition=ScheduleDefinition(
            predicate_subject="test.subject",
            predicate_operator="eq",
            predicate_value="value",
            evaluation_interval_count=10,
        ),
    )

    with pytest.raises(SchedulerAdapterError) as exc:
        adapter.register_schedule(payload)

    # Validation layer catches this before adapter-specific logic
    assert exc.value.code == "invalid_schedule_definition"


def test_register_conditional_unsupported_interval_unit_is_rejected() -> None:
    """Ensure conditional schedules reject unsupported evaluation interval units."""
    client = _FakeCeleryClient()
    adapter = _adapter_with_evaluation_callback(client)
    payload = SchedulePayload(
        schedule_id=608,
        schedule_type="conditional",
        timezone="UTC",
        definition=ScheduleDefinition(
            predicate_subject="test.subject",
            predicate_operator="eq",
            predicate_value="value",
            evaluation_interval_count=1,
            evaluation_interval_unit="month",  # Not supported
        ),
    )

    with pytest.raises(SchedulerAdapterError) as exc:
        adapter.register_schedule(payload)

    # Validation layer catches this before adapter-specific logic
    assert exc.value.code == "invalid_schedule_definition"


def test_update_conditional_schedule() -> None:
    """Ensure conditional schedules can be updated via the adapter."""
    client = _FakeCeleryClient()
    adapter = _adapter_with_evaluation_callback(client)
    payload = SchedulePayload(
        schedule_id=609,
        schedule_type="conditional",
        timezone="UTC",
        definition=ScheduleDefinition(
            predicate_subject="updated.subject",
            predicate_operator="neq",
            predicate_value="old_value",
            evaluation_interval_count=30,
            evaluation_interval_unit="minute",
        ),
    )

    adapter.update_schedule(payload)

    entry = client.updated[-1]
    assert entry.name == "schedule:609"
    assert entry.task == "scheduler.evaluate_predicate"
    assert isinstance(entry.schedule, CeleryIntervalSchedule)
    assert entry.schedule.every == 30
    assert entry.schedule.period == "minutes"


def test_pause_resume_delete_works_for_all_schedule_types() -> None:
    """Ensure pause/resume/delete work consistently for all schedule types."""
    client = _FakeCeleryClient()
    adapter = _adapter_with_evaluation_callback(client)

    # Calendar rule schedule
    adapter.pause_schedule(700)
    adapter.resume_schedule(700)
    adapter.delete_schedule(700)

    # Conditional schedule
    adapter.pause_schedule(701)
    adapter.resume_schedule(701)
    adapter.delete_schedule(701)

    assert client.paused == ["schedule:700", "schedule:701"]
    assert client.resumed == ["schedule:700", "schedule:701"]
    assert client.deleted == ["schedule:700", "schedule:701"]


def test_calendar_rule_with_ordinal_byday() -> None:
    """Ensure BYDAY with ordinal prefix (e.g., 1MO for first Monday) is handled."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    # First Monday of each month
    payload = SchedulePayload(
        schedule_id=801,
        schedule_type="calendar_rule",
        timezone="UTC",
        definition=ScheduleDefinition(rrule="FREQ=MONTHLY;BYDAY=1MO"),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert isinstance(entry.schedule, CeleryCrontabSchedule)
    # Ordinal prefix is stripped, just use the day
    assert entry.schedule.day_of_week == "1"  # Monday


def test_calendar_rule_sunday_mapping() -> None:
    """Ensure Sunday maps correctly to crontab day 0."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    payload = SchedulePayload(
        schedule_id=802,
        schedule_type="calendar_rule",
        timezone="UTC",
        definition=ScheduleDefinition(rrule="FREQ=WEEKLY;BYDAY=SU"),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert isinstance(entry.schedule, CeleryCrontabSchedule)
    assert entry.schedule.day_of_week == "0"  # Sunday


def test_calendar_rule_saturday_mapping() -> None:
    """Ensure Saturday maps correctly to crontab day 6."""
    client = _FakeCeleryClient()
    adapter = _adapter(client)
    payload = SchedulePayload(
        schedule_id=803,
        schedule_type="calendar_rule",
        timezone="UTC",
        definition=ScheduleDefinition(rrule="FREQ=WEEKLY;BYDAY=SA"),
    )

    adapter.register_schedule(payload)

    entry = client.registered[-1]
    assert isinstance(entry.schedule, CeleryCrontabSchedule)
    assert entry.schedule.day_of_week == "6"  # Saturday
