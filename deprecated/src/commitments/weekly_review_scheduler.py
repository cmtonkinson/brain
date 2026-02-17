"""Scheduler setup for weekly commitment review tasks."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Callable

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
from config import settings

_WEEKDAY_TO_RRULE = {
    "monday": ("MO", 0),
    "tuesday": ("TU", 1),
    "wednesday": ("WE", 2),
    "thursday": ("TH", 3),
    "friday": ("FR", 4),
    "saturday": ("SA", 5),
    "sunday": ("SU", 6),
}


def schedule_weekly_review(
    *,
    session_factory,
    adapter: SchedulerAdapter,
    now_provider: Callable[[], datetime] | None = None,
) -> ScheduleMutationResult:
    """Create a weekly review schedule based on configured day/time."""
    now_provider = now_provider or (lambda: datetime.now(timezone.utc))
    review_day = settings.commitments.review_day
    review_time = settings.commitments.review_time
    timezone_name = settings.user.timezone

    rrule, anchor = _build_review_schedule(review_day, review_time, now_provider())

    service = ScheduleCommandServiceImpl(session_factory, adapter, now_provider=now_provider)
    request = ScheduleCreateRequest(
        task_intent=TaskIntentInput(
            summary="Weekly commitment review",
            details="Generate the weekly commitment review summary.",
            origin_reference="commitments.weekly_review",
        ),
        schedule_type="calendar_rule",
        timezone=timezone_name,
        definition=ScheduleDefinitionInput(rrule=rrule, calendar_anchor_at=anchor),
    )
    actor = ActorContext(
        actor_type="system",
        actor_id=None,
        channel="system",
        trace_id="commitments.weekly_review",
    )
    return service.create_schedule(request, actor)


def _build_review_schedule(
    review_day: str,
    review_time: str,
    now: datetime,
) -> tuple[str, datetime]:
    """Build the RRULE and anchor timestamp for the weekly review schedule."""
    rrule_day, weekday_index = _normalize_review_day(review_day)
    hour, minute = _parse_review_time(review_time)
    rrule = f"FREQ=WEEKLY;BYDAY={rrule_day};BYHOUR={hour};BYMINUTE={minute}"

    local_now = to_local(now)
    anchor = _next_weekday_at_time(local_now, weekday_index, hour, minute)
    return rrule, anchor


def _normalize_review_day(value: str) -> tuple[str, int]:
    """Normalize review day strings into RRULE day tokens."""
    normalized = value.strip().lower()
    if normalized not in _WEEKDAY_TO_RRULE:
        raise ValueError("review_day must be a weekday name, e.g., Saturday")
    return _WEEKDAY_TO_RRULE[normalized]


def _parse_review_time(value: str) -> tuple[int, int]:
    """Parse review_time strings into hour/minute components."""
    parsed = datetime.strptime(value.strip(), "%H:%M").time()
    return parsed.hour, parsed.minute


def _next_weekday_at_time(
    now_local: datetime,
    weekday_index: int,
    hour: int,
    minute: int,
) -> datetime:
    """Return the next occurrence of the requested weekday/time in local tz."""
    local_tz = get_local_timezone()
    candidate_date = now_local.date() + timedelta(days=(weekday_index - now_local.weekday()) % 7)
    candidate = datetime.combine(candidate_date, time(hour=hour, minute=minute), tzinfo=local_tz)
    if candidate <= now_local:
        candidate += timedelta(days=7)
    return candidate
