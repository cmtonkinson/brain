"""Unit tests for schedule validation helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scheduler.data_access import ScheduleDefinitionInput
from scheduler.schedule_service_interface import (
    ScheduleConflictError,
    ScheduleImmutableFieldError,
    ScheduleStateTransitionError,
    ScheduleValidationError,
)
from scheduler.schedule_validation import (
    validate_schedule_definition,
    validate_schedule_state_transition,
    validate_task_intent_immutable,
)


def _now() -> datetime:
    """Return a timezone-aware reference time."""
    return datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_one_time_requires_future_run_at() -> None:
    """Ensure one-time schedules require a future run_at."""
    now = _now()
    definition = ScheduleDefinitionInput(run_at=now - timedelta(minutes=1))

    with pytest.raises(ScheduleValidationError):
        validate_schedule_definition(
            "one_time",
            definition,
            now=now,
            require_future_run_at=True,
        )

    validate_schedule_definition(
        "one_time",
        ScheduleDefinitionInput(run_at=now + timedelta(minutes=10)),
        now=now,
        require_future_run_at=True,
    )


def test_interval_requires_positive_count_and_unit() -> None:
    """Ensure interval schedules enforce cadence requirements."""
    with pytest.raises(ScheduleValidationError):
        validate_schedule_definition(
            "interval",
            ScheduleDefinitionInput(interval_count=0, interval_unit="day"),
        )

    with pytest.raises(ScheduleValidationError):
        validate_schedule_definition(
            "interval",
            ScheduleDefinitionInput(interval_count=1, interval_unit=None),
        )


def test_calendar_rule_requires_valid_rrule() -> None:
    """Ensure calendar-rule schedules require a valid RRULE."""
    with pytest.raises(ScheduleValidationError):
        validate_schedule_definition(
            "calendar_rule",
            ScheduleDefinitionInput(rrule="INTERVAL=1"),
        )

    validate_schedule_definition(
        "calendar_rule",
        ScheduleDefinitionInput(rrule="FREQ=DAILY;INTERVAL=1"),
    )


def test_calendar_rule_rejects_unsupported_rrule_freq() -> None:
    """Ensure unsupported RRULE frequencies are rejected."""
    with pytest.raises(ScheduleValidationError):
        validate_schedule_definition(
            "calendar_rule",
            ScheduleDefinitionInput(rrule="FREQ=SECONDLY"),
        )


def test_conditional_requires_predicate_and_cadence() -> None:
    """Ensure conditional schedules require predicate details and cadence."""
    with pytest.raises(ScheduleValidationError):
        validate_schedule_definition(
            "conditional",
            ScheduleDefinitionInput(
                predicate_subject=None,
                predicate_operator="eq",
                predicate_value="ok",
                evaluation_interval_count=1,
                evaluation_interval_unit="hour",
            ),
        )

    with pytest.raises(ScheduleValidationError):
        validate_schedule_definition(
            "conditional",
            ScheduleDefinitionInput(
                predicate_subject="skill.health",
                predicate_operator="eq",
                predicate_value="ok",
                evaluation_interval_count=None,
                evaluation_interval_unit="hour",
            ),
        )


def test_state_transition_validation_blocks_invalid_changes() -> None:
    """Ensure invalid schedule state transitions are rejected."""
    with pytest.raises(ScheduleStateTransitionError):
        validate_schedule_state_transition("paused", "completed")

    with pytest.raises(ScheduleConflictError):
        validate_schedule_state_transition("paused", "paused", allow_noop=False)


def test_task_intent_immutability_validation() -> None:
    """Ensure task intent identifiers remain immutable."""
    with pytest.raises(ScheduleImmutableFieldError):
        validate_task_intent_immutable(10, 11)
