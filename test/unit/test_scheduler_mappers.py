"""Unit tests for the shared scheduler mappers."""

from datetime import datetime, timezone

import pytest

from models import Schedule, TaskIntent
from scheduler.mappers import (
    to_schedule_definition_view,
    to_schedule_view,
    to_task_intent_view,
)
from scheduler.schedule_service_interface import ScheduleConflictError


def _build_schedule(**overrides) -> Schedule:
    event_time = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    defaults = {
        "id": 1,
        "task_intent_id": 2,
        "schedule_type": "one_time",
        "state": "active",
        "timezone": "UTC",
        "next_run_at": event_time,
        "failure_count": 0,
        "created_by_actor_type": "user",
        "created_at": event_time,
        "updated_at": event_time,
    }
    defaults.update(overrides)
    return Schedule(**defaults)


def _build_task_intent(**overrides) -> TaskIntent:
    timestamp = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    defaults = {
        "id": 3,
        "summary": "test intent",
        "creator_actor_type": "user",
        "creator_channel": "signal",
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    defaults.update(overrides)
    return TaskIntent(**defaults)


def test_to_schedule_view_preserves_timezone_and_definition_fields() -> None:
    schedule = _build_schedule(
        timezone="America/New_York",
        rrule="FREQ=DAILY",
        predicate_subject="foo",
        predicate_operator="eq",
        predicate_value="bar",
        evaluation_interval_count=5,
        evaluation_interval_unit="minute",
    )

    view = to_schedule_view(schedule)

    assert view.timezone == "America/New_York"
    assert view.definition.rrule == "FREQ=DAILY"
    assert view.definition.predicate_subject == "foo"
    assert view.definition.evaluation_interval_count == 5


def test_to_schedule_view_missing_timezone_raises_conflict() -> None:
    schedule = _build_schedule(timezone=None)

    with pytest.raises(ScheduleConflictError):
        to_schedule_view(schedule)


def test_to_schedule_definition_view_copies_all_fields() -> None:
    schedule = _build_schedule(
        run_at=datetime(2025, 2, 1, 7, 0, tzinfo=timezone.utc),
        interval_count=2,
        interval_unit="day",
        anchor_at=datetime(2025, 2, 1, 7, 0, tzinfo=timezone.utc),
        rrule="FREQ=WEEKLY",
        calendar_anchor_at=datetime(2025, 2, 1, 7, 0, tzinfo=timezone.utc),
        predicate_subject="status",
        predicate_operator="exists",
        predicate_value="true",
        evaluation_interval_count=1,
        evaluation_interval_unit="hour",
    )

    definition_view = to_schedule_definition_view(schedule)

    assert definition_view.run_at == schedule.run_at
    assert definition_view.interval_unit == "day"
    assert definition_view.rrule == "FREQ=WEEKLY"
    assert definition_view.evaluation_interval_unit == "hour"


def test_to_task_intent_view_preserves_fields() -> None:
    intent = _build_task_intent(
        details="detail text",
        origin_reference="origin",
        creator_actor_id="actor123",
    )

    view = to_task_intent_view(intent)

    assert view.details == "detail text"
    assert view.origin_reference == "origin"
    assert view.creator_actor_id == "actor123"
