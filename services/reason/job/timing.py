"""Schedule timing calculations for next-run computation."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr

from services.reason.job.domain import (
    CalendarRuleDefinition,
    ConditionalDefinition,
    IntervalDefinition,
    IntervalUnit,
    OneTimeDefinition,
    ScheduleDefinition,
    ScheduleType,
)


def compute_next_run(
    schedule_type: ScheduleType,
    definition: ScheduleDefinition,
    *,
    reference_time: datetime,
    timezone_name: str,
) -> datetime | None:
    """Dispatch to the appropriate next-run calculator for ``schedule_type``."""
    reference_time = _ensure_utc(reference_time)

    if schedule_type == ScheduleType.one_time:
        assert isinstance(definition, OneTimeDefinition)
        return _ensure_utc(definition.run_at)

    if schedule_type == ScheduleType.interval:
        assert isinstance(definition, IntervalDefinition)
        return compute_interval_next_run(
            definition,
            reference_time=reference_time,
            timezone_name=timezone_name,
        )

    if schedule_type == ScheduleType.calendar_rule:
        assert isinstance(definition, CalendarRuleDefinition)
        return compute_calendar_rule_next_run(
            definition,
            reference_time=reference_time,
            timezone_name=timezone_name,
        )

    if schedule_type == ScheduleType.conditional:
        assert isinstance(definition, ConditionalDefinition)
        return compute_conditional_next_run(
            definition,
            reference_time=reference_time,
            timezone_name=timezone_name,
        )

    msg = f"unsupported schedule type: {schedule_type}"
    raise ValueError(msg)


def compute_interval_next_run(
    definition: IntervalDefinition,
    *,
    reference_time: datetime,
    timezone_name: str,
) -> datetime | None:
    """Compute the next interval boundary after ``reference_time``."""
    tz = ZoneInfo(timezone_name)
    reference_local = _ensure_utc(reference_time).astimezone(tz)
    anchor_local = (
        _ensure_utc(definition.anchor_at).astimezone(tz)
        if definition.anchor_at is not None
        else reference_local
    )

    if definition.interval_unit in {IntervalUnit.minute, IntervalUnit.hour}:
        delta = _interval_delta(definition.interval_count, definition.interval_unit)
        assert delta is not None
        if anchor_local > reference_local:
            return anchor_local.astimezone(timezone.utc)
        elapsed = reference_local - anchor_local
        elapsed_cycles = elapsed // delta
        next_local = anchor_local + delta * (elapsed_cycles + 1)
        return next_local.astimezone(timezone.utc)

    cursor = anchor_local
    if cursor > reference_local:
        return cursor.astimezone(timezone.utc)
    while cursor <= reference_local:
        cursor = _advance_local_interval(
            cursor,
            count=definition.interval_count,
            unit=definition.interval_unit,
        )
    return cursor.astimezone(timezone.utc)


def compute_calendar_rule_next_run(
    definition: CalendarRuleDefinition,
    *,
    reference_time: datetime,
    timezone_name: str,
) -> datetime | None:
    """Compute the next RRULE occurrence after ``reference_time`` in local time."""
    tz = ZoneInfo(timezone_name)
    reference_local = _ensure_utc(reference_time).astimezone(tz).replace(tzinfo=None)

    dtstart = None
    if definition.calendar_anchor_at is not None:
        dtstart = (
            _ensure_utc(definition.calendar_anchor_at)
            .astimezone(tz)
            .replace(tzinfo=None)
        )

    kwargs: dict[str, object] = {"ignoretz": True}
    if dtstart is not None:
        kwargs["dtstart"] = dtstart

    rule = rrulestr(definition.rrule, **kwargs)
    result = rule.after(reference_local, inc=False)
    if result is None:
        return None
    return result.replace(tzinfo=tz).astimezone(timezone.utc)


def compute_conditional_next_run(
    definition: ConditionalDefinition,
    *,
    reference_time: datetime,
    timezone_name: str,
) -> datetime | None:
    """Compute the next evaluation time for a conditional schedule."""
    interval = IntervalDefinition(
        interval_count=definition.evaluation_interval_count,
        interval_unit=definition.evaluation_interval_unit,
        anchor_at=reference_time,
    )
    return compute_interval_next_run(
        interval,
        reference_time=reference_time,
        timezone_name=timezone_name,
    )


def _ensure_utc(value: datetime) -> datetime:
    """Normalize a datetime to UTC; assume UTC if naive."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _interval_delta(count: int, unit: IntervalUnit) -> timedelta | None:
    """Convert an interval count+unit to a timedelta when calendar-safe."""
    if unit == IntervalUnit.minute:
        return timedelta(minutes=count)
    if unit == IntervalUnit.hour:
        return timedelta(hours=count)
    if unit in {IntervalUnit.day, IntervalUnit.week, IntervalUnit.month}:
        return None
    msg = f"unsupported interval unit: {unit}"
    raise ValueError(msg)


def _advance_local_interval(
    value: datetime, *, count: int, unit: IntervalUnit
) -> datetime:
    """Advance one local datetime by the given interval unit."""
    if unit == IntervalUnit.day:
        return value + timedelta(days=count)
    if unit == IntervalUnit.week:
        return value + timedelta(weeks=count)
    if unit == IntervalUnit.month:
        return _add_months(value, count)
    msg = f"unsupported local interval unit: {unit}"
    raise ValueError(msg)


def _add_months(value: datetime, months: int) -> datetime:
    """Add ``months`` to ``value``, clamping day to month-end if necessary."""
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(value.day, max_day)
    return value.replace(year=year, month=month, day=day)
