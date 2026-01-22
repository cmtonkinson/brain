"""Reusable helpers for computing schedule cadences and next-run timestamps."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from dateutil.rrule import rrulestr

from scheduler.schedule_validation import ScheduleDefinitionLike

LOGGER = logging.getLogger(__name__)


def compute_next_run_for_definition(
    schedule_type: str,
    definition: ScheduleDefinitionLike,
    *,
    reference_time: datetime,
) -> datetime | None:
    """Return the next run timestamp for a schedule definition after a reference time."""
    reference = _ensure_timezone(reference_time, reference_time.tzinfo)
    if schedule_type == "one_time":
        return _one_time_next_run(definition.run_at, reference.tzinfo)
    if schedule_type == "interval":
        return compute_interval_next_run(
            definition.interval_count,
            definition.interval_unit,
            definition.anchor_at,
            reference_time=reference,
        )
    if schedule_type == "calendar_rule":
        return compute_calendar_rule_next_run(
            definition.rrule,
            definition.calendar_anchor_at,
            reference_time=reference,
        )
    if schedule_type == "conditional":
        return compute_conditional_next_run(
            definition.evaluation_interval_count,
            definition.evaluation_interval_unit,
            reference_time=reference,
        )
    return None


def compute_interval_next_run(
    interval_count: int | None,
    interval_unit: str | None,
    anchor_at: datetime | None,
    *,
    reference_time: datetime,
) -> datetime | None:
    """Compute the next interval occurrence after a reference timestamp."""
    if interval_count is None or interval_count <= 0 or interval_unit is None:
        return None
    reference = _ensure_timezone(reference_time, reference_time.tzinfo)
    anchor = anchor_at or reference
    anchor = _ensure_timezone(anchor, reference.tzinfo)
    if anchor > reference:
        return anchor
    if interval_unit == "month":
        current = anchor
        while current <= reference:
            current = _add_months(current, interval_count)
        return current
    step = _interval_delta(interval_count, interval_unit)
    if step is None or step.total_seconds() <= 0:
        return None
    elapsed_cycles = (reference - anchor) // step
    return anchor + step * (elapsed_cycles + 1)


def compute_calendar_rule_next_run(
    rrule_value: str | None,
    calendar_anchor_at: datetime | None,
    *,
    reference_time: datetime,
) -> datetime | None:
    """Compute the next calendar rule occurrence after the reference timestamp."""
    if not rrule_value:
        return None
    reference = _ensure_timezone(reference_time, reference_time.tzinfo)
    anchor = calendar_anchor_at or reference
    anchor = _ensure_timezone(anchor, reference.tzinfo)
    try:
        rule = rrulestr(rrule_value, dtstart=anchor)
    except Exception as exc:
        LOGGER.warning("Failed to parse RRULE '%s': %s", rrule_value, exc)
        return None
    next_occurrence = rule.after(reference, inc=False)
    if next_occurrence is None:
        return None
    return _ensure_timezone(next_occurrence, reference.tzinfo)


def compute_conditional_next_run(
    evaluation_interval_count: int | None,
    evaluation_interval_unit: str | None,
    *,
    reference_time: datetime,
) -> datetime | None:
    """Compute the next conditional evaluation time after the reference timestamp."""
    if (
        evaluation_interval_count is None
        or evaluation_interval_count <= 0
        or evaluation_interval_unit is None
    ):
        return None
    step = _interval_delta(evaluation_interval_count, evaluation_interval_unit)
    if step is None or step.total_seconds() <= 0:
        return None
    reference = _ensure_timezone(reference_time, reference_time.tzinfo)
    return reference + step


def _one_time_next_run(value: datetime | None, tzinfo: timezone | None) -> datetime | None:
    if value is None:
        return None
    return _ensure_timezone(value, tzinfo)


def _ensure_timezone(value: datetime, tzinfo: timezone | None) -> datetime:
    target = tzinfo or timezone.utc
    if value.tzinfo is None:
        return value.replace(tzinfo=target)
    return value.astimezone(target)


def _interval_delta(count: int, unit: str) -> timedelta | None:
    if unit == "minute":
        return timedelta(minutes=count)
    if unit == "hour":
        return timedelta(hours=count)
    if unit == "day":
        return timedelta(days=count)
    if unit == "week":
        return timedelta(weeks=count)
    return None


def _add_months(value: datetime, months: int) -> datetime:
    """Return a datetime advanced by the requested number of months."""
    total_month = value.month - 1 + months
    year = value.year + total_month // 12
    month = total_month % 12 + 1
    day = min(value.day, _days_in_month(year, month))
    return value.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    current_month = datetime(year, month, 1, tzinfo=timezone.utc)
    return (next_month - current_month).days
