"""Unit tests for the schedule service interface module."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from scheduler.schedule_service_interface import (
    ExecutionRunNowResult,
    ExecutionView,
    ScheduleCreateRequest,
    ScheduleDefinitionInput,
    ScheduleDefinitionView,
    ScheduleMutationResult,
    ScheduleServiceError,
    ScheduleValidationError,
    ScheduleView,
    TaskIntentInput,
    TaskIntentView,
)


def _now() -> datetime:
    """Return a timezone-aware timestamp for tests."""
    return datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def _task_intent_view() -> TaskIntentView:
    """Return a sample task intent view."""
    now = _now()
    return TaskIntentView(
        id=10,
        summary="Daily brief",
        details=None,
        origin_reference=None,
        creator_actor_type="human",
        creator_actor_id="user-1",
        creator_channel="signal",
        created_at=now,
        superseded_by_intent_id=None,
    )


def _schedule_view() -> ScheduleView:
    """Return a sample schedule view."""
    now = _now()
    definition = ScheduleDefinitionView(run_at=now)
    return ScheduleView(
        id=20,
        task_intent_id=10,
        schedule_type="one_time",
        state="active",
        timezone="UTC",
        definition=definition,
        next_run_at=now,
        last_run_at=None,
        last_run_status=None,
        failure_count=0,
        created_at=now,
        created_by_actor_type="human",
        created_by_actor_id="user-1",
        updated_at=now,
        last_execution_id=None,
        last_evaluated_at=None,
        last_evaluation_status=None,
        last_evaluation_error_code=None,
    )


def test_schedule_create_request_is_frozen() -> None:
    """Ensure schedule create requests are immutable."""
    request = ScheduleCreateRequest(
        task_intent=TaskIntentInput(summary="Follow up"),
        schedule_type="one_time",
        timezone="UTC",
        definition=ScheduleDefinitionInput(run_at=_now()),
    )

    with pytest.raises(FrozenInstanceError):
        request.schedule_type = "interval"


def test_schedule_mutation_result_is_frozen() -> None:
    """Ensure schedule mutation results are immutable."""
    result = ScheduleMutationResult(
        schedule=_schedule_view(),
        task_intent=_task_intent_view(),
        audit_log_id=55,
    )

    with pytest.raises(FrozenInstanceError):
        result.schedule = _schedule_view()


def test_execution_run_now_result_is_frozen() -> None:
    """Ensure run-now execution results are immutable."""
    now = _now()
    execution = ExecutionView(
        id=30,
        schedule_id=20,
        task_intent_id=10,
        scheduled_for=now,
        status="queued",
        attempt_number=0,
        max_attempts=1,
        created_at=now,
        actor_type="scheduled",
        correlation_id="corr-1",
    )
    result = ExecutionRunNowResult(execution=execution, audit_log_id=99)

    with pytest.raises(FrozenInstanceError):
        result.audit_log_id = 100


def test_schedule_service_error_exposes_code_and_details() -> None:
    """Ensure schedule service errors expose structured metadata."""
    err = ScheduleServiceError("custom_error", "Something went wrong.", {"field": "value"})
    validation = ScheduleValidationError("Invalid schedule.")

    assert err.code == "custom_error"
    assert err.details == {"field": "value"}
    assert validation.code == "validation_error"
