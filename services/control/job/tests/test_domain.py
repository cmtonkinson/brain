"""Tests for Job Service domain models, enums, and state machine."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from services.control.job.domain import (
    ALLOWED_STATE_TRANSITIONS,
    AuditEventType,
    BackoffStrategy,
    CalendarRuleDefinition,
    CapabilityInvocationAction,
    ConditionalDefinition,
    ExecutionStatus,
    IntervalDefinition,
    IntervalUnit,
    JobState,
    OneTimeDefinition,
    PredicateOperator,
    ScheduleType,
    job_action_adapter,
    schedule_definition_adapter,
)


# ---------------------------------------------------------------------------
# Enum value coverage
# ---------------------------------------------------------------------------


class TestEnumValues:
    """Verify all enum members have expected string values."""

    def test_schedule_type_values(self) -> None:
        assert {t.value for t in ScheduleType} == {
            "one_time",
            "interval",
            "calendar_rule",
            "conditional",
        }

    def test_job_state_values(self) -> None:
        assert {s.value for s in JobState} == {
            "draft",
            "active",
            "paused",
            "canceled",
            "archived",
            "completed",
        }

    def test_execution_status_values(self) -> None:
        assert {s.value for s in ExecutionStatus} == {
            "queued",
            "running",
            "succeeded",
            "failed",
            "retry_scheduled",
            "canceled",
        }

    def test_job_action_type_values(self) -> None:
        restored = job_action_adapter.validate_python(
            {
                "type": "capability_invocation",
                "capability_id": "demo-capability",
                "input_payload": {"message": "hello"},
            }
        )
        assert isinstance(restored, CapabilityInvocationAction)

    def test_backoff_strategy_values(self) -> None:
        assert {s.value for s in BackoffStrategy} == {"fixed", "exponential", "none"}

    def test_predicate_operator_values(self) -> None:
        assert {o.value for o in PredicateOperator} == {
            "eq",
            "neq",
            "gt",
            "gte",
            "lt",
            "lte",
            "exists",
            "matches",
        }

    def test_interval_unit_values(self) -> None:
        assert {u.value for u in IntervalUnit} == {
            "minute",
            "hour",
            "day",
            "week",
            "month",
        }

    def test_audit_event_type_values(self) -> None:
        assert {e.value for e in AuditEventType} == {
            "create",
            "update",
            "pause",
            "resume",
            "delete",
            "run_now",
        }


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class TestStateTransitions:
    """Verify allowed and disallowed state transitions."""

    @pytest.mark.parametrize(
        "current,target",
        [
            (JobState.draft, JobState.active),
            (JobState.active, JobState.paused),
            (JobState.active, JobState.canceled),
            (JobState.active, JobState.completed),
            (JobState.paused, JobState.active),
            (JobState.paused, JobState.canceled),
            (JobState.canceled, JobState.archived),
            (JobState.completed, JobState.archived),
        ],
    )
    def test_valid_transitions(self, current: JobState, target: JobState) -> None:
        assert target in ALLOWED_STATE_TRANSITIONS[current]

    @pytest.mark.parametrize(
        "current,target",
        [
            (JobState.draft, JobState.paused),
            (JobState.draft, JobState.canceled),
            (JobState.active, JobState.draft),
            (JobState.active, JobState.archived),
            (JobState.paused, JobState.completed),
            (JobState.paused, JobState.draft),
            (JobState.canceled, JobState.active),
            (JobState.completed, JobState.active),
            (JobState.archived, JobState.active),
        ],
    )
    def test_invalid_transitions(self, current: JobState, target: JobState) -> None:
        assert target not in ALLOWED_STATE_TRANSITIONS[current]

    def test_archived_is_terminal(self) -> None:
        assert len(ALLOWED_STATE_TRANSITIONS[JobState.archived]) == 0


# ---------------------------------------------------------------------------
# Schedule definitions (discriminated union)
# ---------------------------------------------------------------------------


class TestScheduleDefinitions:
    """Verify discriminated union construction and round-trip."""

    def test_one_time_round_trip(self) -> None:
        d = OneTimeDefinition(run_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
        data = d.model_dump(mode="python")
        assert data["type"] == "one_time"
        restored = schedule_definition_adapter.validate_python(data)
        assert isinstance(restored, OneTimeDefinition)
        assert restored.run_at == d.run_at

    def test_interval_round_trip(self) -> None:
        d = IntervalDefinition(interval_count=5, interval_unit=IntervalUnit.hour)
        data = d.model_dump(mode="python")
        assert data["type"] == "interval"
        restored = schedule_definition_adapter.validate_python(data)
        assert isinstance(restored, IntervalDefinition)
        assert restored.interval_count == 5

    def test_calendar_rule_round_trip(self) -> None:
        d = CalendarRuleDefinition(rrule="FREQ=DAILY;INTERVAL=1")
        data = d.model_dump(mode="python")
        assert data["type"] == "calendar_rule"
        restored = schedule_definition_adapter.validate_python(data)
        assert isinstance(restored, CalendarRuleDefinition)
        assert "DAILY" in restored.rrule

    def test_conditional_round_trip(self) -> None:
        d = ConditionalDefinition(
            predicate_capability_id="predicate-read",
            predicate_subject="vault.read/status",
            predicate_operator=PredicateOperator.eq,
            predicate_value="ready",
            evaluation_interval_count=10,
            evaluation_interval_unit=IntervalUnit.minute,
        )
        data = d.model_dump(mode="python")
        assert data["type"] == "conditional"
        restored = schedule_definition_adapter.validate_python(data)
        assert isinstance(restored, ConditionalDefinition)
        assert restored.predicate_subject == "vault.read/status"

    def test_conditional_requires_value_for_comparison(self) -> None:
        with pytest.raises(ValidationError, match="predicate_value is required"):
            ConditionalDefinition(
                predicate_capability_id="predicate-read",
                predicate_subject="x",
                predicate_operator=PredicateOperator.eq,
                predicate_value=None,
                evaluation_interval_count=1,
                evaluation_interval_unit=IntervalUnit.hour,
            )

    def test_conditional_exists_allows_no_value(self) -> None:
        d = ConditionalDefinition(
            predicate_capability_id="predicate-read",
            predicate_subject="x",
            predicate_operator=PredicateOperator.exists,
            predicate_value=None,
            evaluation_interval_count=1,
            evaluation_interval_unit=IntervalUnit.hour,
        )
        assert d.predicate_value is None

    def test_interval_rejects_zero_count(self) -> None:
        with pytest.raises(ValidationError):
            IntervalDefinition(interval_count=0, interval_unit=IntervalUnit.day)

    def test_frozen_model_rejects_assignment(self) -> None:
        d = OneTimeDefinition(run_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
        with pytest.raises(ValidationError):
            d.run_at = datetime(2026, 7, 1, tzinfo=timezone.utc)  # type: ignore[misc]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OneTimeDefinition(
                run_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                bogus="nope",  # type: ignore[call-arg]
            )
