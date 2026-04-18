"""Tests for Job Service schedule timing calculations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from services.control.job.domain import (
    CalendarRuleDefinition,
    ConditionalDefinition,
    IntervalDefinition,
    IntervalUnit,
    OneTimeDefinition,
    PredicateOperator,
    ScheduleType,
)
from services.control.job.timing import (
    _add_months,
    compute_calendar_rule_next_run,
    compute_conditional_next_run,
    compute_interval_next_run,
    compute_next_run,
)


_UTC = timezone.utc


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=_UTC)


# ---------------------------------------------------------------------------
# One-time
# ---------------------------------------------------------------------------


class TestOneTimeNextRun:
    """One-time schedule returns run_at normalized to UTC."""

    def test_returns_run_at(self) -> None:
        run_at = _utc(2026, 7, 1, 12)
        d = OneTimeDefinition(run_at=run_at)
        result = compute_next_run(
            ScheduleType.one_time,
            d,
            reference_time=_utc(2026, 1, 1),
            timezone_name="UTC",
        )
        assert result == run_at


# ---------------------------------------------------------------------------
# Interval
# ---------------------------------------------------------------------------


class TestIntervalNextRun:
    """Interval schedule next-run calculation."""

    def test_minute_interval(self) -> None:
        d = IntervalDefinition(interval_count=30, interval_unit=IntervalUnit.minute)
        ref = _utc(
            2026,
            1,
            1,
            10,
        )
        result = compute_interval_next_run(d, reference_time=ref, timezone_name="UTC")
        assert result == ref + timedelta(minutes=30)

    def test_hour_interval(self) -> None:
        d = IntervalDefinition(interval_count=2, interval_unit=IntervalUnit.hour)
        ref = _utc(2026, 1, 1, 10)
        result = compute_interval_next_run(d, reference_time=ref, timezone_name="UTC")
        assert result == ref + timedelta(hours=2)

    def test_day_interval(self) -> None:
        d = IntervalDefinition(interval_count=7, interval_unit=IntervalUnit.day)
        ref = _utc(2026, 1, 1)
        result = compute_interval_next_run(d, reference_time=ref, timezone_name="UTC")
        assert result == ref + timedelta(days=7)

    def test_week_interval(self) -> None:
        d = IntervalDefinition(interval_count=1, interval_unit=IntervalUnit.week)
        ref = _utc(2026, 1, 1)
        result = compute_interval_next_run(d, reference_time=ref, timezone_name="UTC")
        assert result == ref + timedelta(weeks=1)

    def test_with_past_anchor(self) -> None:
        anchor = _utc(2026, 1, 1)
        d = IntervalDefinition(
            interval_count=1, interval_unit=IntervalUnit.day, anchor_at=anchor
        )
        ref = _utc(2026, 1, 5, 12)
        result = compute_interval_next_run(d, reference_time=ref, timezone_name="UTC")
        assert result == _utc(2026, 1, 6)

    def test_with_future_anchor(self) -> None:
        anchor = _utc(2026, 6, 1)
        d = IntervalDefinition(
            interval_count=1, interval_unit=IntervalUnit.day, anchor_at=anchor
        )
        ref = _utc(2026, 1, 1)
        result = compute_interval_next_run(d, reference_time=ref, timezone_name="UTC")
        assert result == anchor


class TestMonthInterval:
    """Month interval with calendar-aware arithmetic."""

    def test_basic_month(self) -> None:
        d = IntervalDefinition(interval_count=1, interval_unit=IntervalUnit.month)
        ref = _utc(2026, 1, 15)
        result = compute_interval_next_run(d, reference_time=ref, timezone_name="UTC")
        assert result == _utc(2026, 2, 15)

    def test_jan31_plus_one_month(self) -> None:
        result = _add_months(_utc(2026, 1, 31), 1)
        assert result == _utc(2026, 2, 28)

    def test_jan31_plus_one_month_leap_year(self) -> None:
        result = _add_months(_utc(2028, 1, 31), 1)
        assert result == _utc(2028, 2, 29)

    def test_mar31_plus_one_month(self) -> None:
        result = _add_months(_utc(2026, 3, 31), 1)
        assert result == _utc(2026, 4, 30)

    def test_twelve_months(self) -> None:
        result = _add_months(_utc(2026, 1, 15), 12)
        assert result == _utc(2027, 1, 15)


# ---------------------------------------------------------------------------
# Calendar rule (RRULE)
# ---------------------------------------------------------------------------


class TestCalendarRuleNextRun:
    """Calendar-rule schedule using dateutil RRULE parsing."""

    def test_daily(self) -> None:
        d = CalendarRuleDefinition(rrule="FREQ=DAILY;INTERVAL=1")
        ref = _utc(2026, 1, 1, 12)
        result = compute_calendar_rule_next_run(
            d, reference_time=ref, timezone_name="UTC"
        )
        assert result is not None
        assert result > ref

    def test_weekly(self) -> None:
        d = CalendarRuleDefinition(rrule="FREQ=WEEKLY;BYDAY=MO")
        ref = _utc(2026, 1, 5, 12)  # Monday
        result = compute_calendar_rule_next_run(
            d, reference_time=ref, timezone_name="UTC"
        )
        assert result is not None
        assert result > ref

    def test_with_anchor(self) -> None:
        anchor = _utc(2026, 1, 1, 6)
        d = CalendarRuleDefinition(
            rrule="FREQ=DAILY;INTERVAL=1", calendar_anchor_at=anchor
        )
        ref = _utc(2026, 1, 1, 3)
        result = compute_calendar_rule_next_run(
            d, reference_time=ref, timezone_name="UTC"
        )
        assert result is not None
        assert result >= anchor


# ---------------------------------------------------------------------------
# Conditional
# ---------------------------------------------------------------------------


class TestConditionalNextRun:
    """Conditional schedule evaluation cadence."""

    def test_minute_cadence(self) -> None:
        d = ConditionalDefinition(
            predicate_capability_id="predicate-read",
            predicate_subject="x",
            predicate_operator=PredicateOperator.exists,
            evaluation_interval_count=15,
            evaluation_interval_unit=IntervalUnit.minute,
        )
        ref = _utc(2026, 1, 1, 10)
        result = compute_conditional_next_run(
            d,
            reference_time=ref,
            timezone_name="UTC",
        )
        assert result == ref + timedelta(minutes=15)

    def test_month_cadence(self) -> None:
        d = ConditionalDefinition(
            predicate_capability_id="predicate-read",
            predicate_subject="x",
            predicate_operator=PredicateOperator.exists,
            evaluation_interval_count=1,
            evaluation_interval_unit=IntervalUnit.month,
        )
        ref = _utc(2026, 1, 15)
        result = compute_conditional_next_run(
            d,
            reference_time=ref,
            timezone_name="UTC",
        )
        assert result == _utc(2026, 2, 15)
