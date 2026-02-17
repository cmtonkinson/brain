"""Scheduler setup for daily batch reminder tasks."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Callable

from config import settings
from scheduler.adapter_interface import SchedulerAdapter
from scheduler.schedule_service import ScheduleCommandServiceImpl
from scheduler.schedule_service_interface import (
    ActorContext,
    ScheduleCreateRequest,
    ScheduleDefinitionInput,
    ScheduleMutationResult,
    TaskIntentInput,
)
from time_utils import get_local_timezone, to_local


def schedule_daily_batch_reminder(
    *,
    session_factory,
    adapter: SchedulerAdapter,
    now_provider: Callable[[], datetime] | None = None,
) -> ScheduleMutationResult:
    """Create a daily batch reminder schedule based on configured time."""
    now_provider = now_provider or (lambda: datetime.now(timezone.utc))
    batch_time = settings.commitments.batch_reminder_time
    timezone_name = settings.user.timezone

    rrule, anchor = _build_batch_schedule(batch_time, now_provider())

    service = ScheduleCommandServiceImpl(session_factory, adapter, now_provider=now_provider)
    request = ScheduleCreateRequest(
        task_intent=TaskIntentInput(
            summary="Daily commitment reminders",
            details="Generate the daily batch reminder digest.",
            origin_reference="commitments.daily_batch",
        ),
        schedule_type="calendar_rule",
        timezone=timezone_name,
        definition=ScheduleDefinitionInput(rrule=rrule, calendar_anchor_at=anchor),
    )
    actor = ActorContext(
        actor_type="system",
        actor_id=None,
        channel="system",
        trace_id="commitments.daily_batch",
    )
    return service.create_schedule(request, actor)


def _build_batch_schedule(batch_time: str, now: datetime) -> tuple[str, datetime]:
    """Build the RRULE and anchor timestamp for the daily batch schedule."""
    hour, minute = _parse_batch_time(batch_time)
    rrule = f"FREQ=DAILY;BYHOUR={hour};BYMINUTE={minute}"

    local_now = to_local(now)
    anchor = _next_time(local_now, hour, minute)
    return rrule, anchor


def _parse_batch_time(value: str) -> tuple[int, int]:
    """Parse batch_reminder_time strings into hour/minute components."""
    parsed = datetime.strptime(value.strip(), "%H:%M").time()
    return parsed.hour, parsed.minute


def _next_time(now_local: datetime, hour: int, minute: int) -> datetime:
    """Return the next local datetime matching the batch time."""
    local_tz = get_local_timezone()
    candidate = datetime.combine(now_local.date(), time(hour=hour, minute=minute), tzinfo=local_tz)
    if candidate <= now_local:
        candidate += timedelta(days=1)
    return candidate
