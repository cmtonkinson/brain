"""Reusable validation helpers for schedule command inputs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from models import (
    EvaluationIntervalUnitEnum,
    IntervalUnitEnum,
    PredicateOperatorEnum,
    ScheduleStateEnum,
    ScheduleTypeEnum,
)
from scheduler.schedule_service_interface import (
    ScheduleConflictError,
    ScheduleImmutableFieldError,
    ScheduleStateTransitionError,
    ScheduleValidationError,
)

_ALLOWED_STATE_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active"},
    "active": {"paused", "canceled", "completed"},
    "paused": {"active", "canceled"},
    "canceled": {"archived"},
    "completed": {"archived"},
    "archived": set(),
}

_ALLOWED_RRULE_FREQUENCIES = {
    "MINUTELY",
    "HOURLY",
    "DAILY",
    "WEEKLY",
    "MONTHLY",
    "YEARLY",
}


class ScheduleDefinitionLike(Protocol):
    """Protocol for schedule definition payloads used by validation."""

    run_at: datetime | None
    interval_count: int | None
    interval_unit: str | None
    anchor_at: datetime | None
    rrule: str | None
    calendar_anchor_at: datetime | None
    predicate_subject: str | None
    predicate_operator: str | None
    predicate_value: object | None
    evaluation_interval_count: int | None
    evaluation_interval_unit: str | None


def _normalize_timestamp(value: datetime, label: str) -> datetime:
    """Ensure timestamps are timezone-aware, defaulting to UTC if naive."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _require_non_empty(value: str | None, field: str) -> str:
    """Ensure a string field is present and non-empty."""
    if value is None or not value.strip():
        raise ScheduleValidationError(f"{field} is required.", {"field": field})
    return value


def _parse_rrule(rrule: str) -> dict[str, str]:
    """Parse a minimal RRULE string into key/value pairs."""
    raw = rrule.strip()
    if not raw:
        raise ScheduleValidationError(
            "rrule is required for calendar_rule schedules.", {"field": "rrule"}
        )
    parts: dict[str, str] = {}
    for segment in raw.split(";"):
        if not segment.strip():
            continue
        if "=" not in segment:
            raise ScheduleValidationError(
                "rrule must use key=value segments.",
                {"field": "rrule", "segment": segment},
            )
        key, value = segment.split("=", 1)
        key = key.strip().upper()
        value = value.strip().upper()
        if not key or not value:
            raise ScheduleValidationError(
                "rrule segments must include key and value.",
                {"field": "rrule", "segment": segment},
            )
        parts[key] = value
    return parts


def validate_timezone(timezone_name: str) -> None:
    """Validate that the timezone name resolves to a ZoneInfo entry."""
    _require_non_empty(timezone_name, "timezone")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ScheduleValidationError(
            f"Invalid timezone: {timezone_name}.",
            {"field": "timezone", "timezone": timezone_name},
        ) from exc


def validate_schedule_type(schedule_type: str) -> None:
    """Validate schedule type against allowed values."""
    if schedule_type not in ScheduleTypeEnum.enums:
        raise ScheduleValidationError(
            f"Invalid schedule_type: {schedule_type}.",
            {"field": "schedule_type", "schedule_type": schedule_type},
        )


def validate_schedule_state(state: str) -> None:
    """Validate schedule state against allowed values."""
    if state not in ScheduleStateEnum.enums:
        raise ScheduleValidationError(
            f"Invalid schedule state: {state}.",
            {"field": "state", "state": state},
        )


def validate_task_intent_immutable(
    existing_task_intent_id: int, proposed_task_intent_id: int | None
) -> None:
    """Reject attempts to change task intent identifiers."""
    if proposed_task_intent_id is None:
        return
    if proposed_task_intent_id != existing_task_intent_id:
        raise ScheduleImmutableFieldError(
            "task_intent_id is immutable after schedule creation.",
            {"field": "task_intent_id"},
        )


def validate_schedule_state_transition(
    current_state: str,
    target_state: str,
    *,
    allow_noop: bool = True,
) -> None:
    """Validate schedule state transitions against the domain model."""
    validate_schedule_state(current_state)
    validate_schedule_state(target_state)
    if current_state == target_state:
        if allow_noop:
            return
        raise ScheduleConflictError(
            f"Schedule already in state '{current_state}'.",
            {"current_state": current_state, "target_state": target_state},
        )
    allowed = _ALLOWED_STATE_TRANSITIONS.get(current_state, set())
    if target_state not in allowed:
        raise ScheduleStateTransitionError(
            f"Invalid schedule state transition from '{current_state}' to '{target_state}'.",
            {"current_state": current_state, "target_state": target_state},
        )


def validate_schedule_definition(
    schedule_type: str,
    definition: ScheduleDefinitionLike,
    *,
    now: datetime | None = None,
    require_future_run_at: bool = False,
) -> None:
    """Validate schedule definition fields based on schedule type."""
    validate_schedule_type(schedule_type)

    current_time = None
    if now is not None:
        current_time = _normalize_timestamp(now, "now")

    if schedule_type == "one_time":
        if definition.run_at is None:
            raise ScheduleValidationError(
                "run_at is required for one_time schedules.",
                {"field": "run_at"},
            )
        run_at = _normalize_timestamp(definition.run_at, "run_at")
        if require_future_run_at and current_time is not None and run_at <= current_time:
            raise ScheduleValidationError(
                "run_at must be in the future for one_time schedules.",
                {"field": "run_at", "run_at": run_at.isoformat()},
            )
    elif schedule_type == "interval":
        if definition.interval_count is None or definition.interval_count <= 0:
            raise ScheduleValidationError(
                "interval_count is required and must be > 0.",
                {"field": "interval_count"},
            )
        if (
            definition.interval_unit is None
            or definition.interval_unit not in IntervalUnitEnum.enums
        ):
            raise ScheduleValidationError(
                "interval_unit is required and must be valid.",
                {"field": "interval_unit"},
            )
    elif schedule_type == "calendar_rule":
        rule = _require_non_empty(definition.rrule, "rrule")
        parts = _parse_rrule(rule)
        freq = parts.get("FREQ")
        if freq is None or freq not in _ALLOWED_RRULE_FREQUENCIES:
            raise ScheduleValidationError(
                "rrule must include a valid FREQ value.",
                {"field": "rrule", "allowed": sorted(_ALLOWED_RRULE_FREQUENCIES)},
            )
    elif schedule_type == "conditional":
        _require_non_empty(definition.predicate_subject, "predicate_subject")
        if (
            definition.predicate_operator is None
            or definition.predicate_operator not in PredicateOperatorEnum.enums
        ):
            raise ScheduleValidationError(
                "predicate_operator is required and must be valid.",
                {"field": "predicate_operator"},
            )
        if definition.predicate_operator != "exists":
            value = definition.predicate_value
            if value is None:
                raise ScheduleValidationError(
                    "predicate_value is required for conditional schedules.",
                    {"field": "predicate_value"},
                )
            if isinstance(value, str) and not value.strip():
                raise ScheduleValidationError(
                    "predicate_value must be non-empty when provided.",
                    {"field": "predicate_value"},
                )
            if not isinstance(value, (str, int, float)):
                raise ScheduleValidationError(
                    "predicate_value must be a string or numeric literal.",
                    {"field": "predicate_value"},
                )
        if (
            definition.evaluation_interval_count is None
            or definition.evaluation_interval_count <= 0
        ):
            raise ScheduleValidationError(
                "evaluation_interval_count is required and must be > 0.",
                {"field": "evaluation_interval_count"},
            )
        if (
            definition.evaluation_interval_unit is None
            or definition.evaluation_interval_unit not in EvaluationIntervalUnitEnum.enums
        ):
            raise ScheduleValidationError(
                "evaluation_interval_unit is required and must be valid.",
                {"field": "evaluation_interval_unit"},
            )
