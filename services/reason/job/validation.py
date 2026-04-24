"""Request validation models for Job Service public API inputs."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pydantic import ValidationError as PydanticValidationError

from services.reason.job.domain import (
    IntervalUnit,
    JobState,
    PredicateOperator,
    ScheduleType,
    job_action_adapter,
)


# ---------------------------------------------------------------------------
# Pagination constants
# ---------------------------------------------------------------------------

_MAX_PAGE_SIZE = 200

# ---------------------------------------------------------------------------
# RRULE frequency whitelist
# ---------------------------------------------------------------------------

_ALLOWED_RRULE_FREQUENCIES = frozenset(
    {"MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"}
)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class _ValidationModel(BaseModel):
    """Base request model with strict shape semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Command requests
# ---------------------------------------------------------------------------


class CreateJobRequest(_ValidationModel):
    """Validated create-job request shape."""

    summary: str = Field(min_length=1, max_length=512)
    details: str | None = None
    origin_reference: str | None = None
    schedule_type: str
    timezone: str
    definition: dict[str, object]
    job_action: dict[str, object]
    start_state: str = JobState.draft.value

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        """Validate timezone is a recognized IANA zone."""
        normalized = value.strip()
        if not normalized:
            msg = "timezone is required"
            raise ValueError(msg)
        try:
            ZoneInfo(normalized)
        except (KeyError, ValueError) as exc:
            msg = f"invalid timezone: {normalized}"
            raise ValueError(msg) from exc
        return normalized

    @field_validator("schedule_type")
    @classmethod
    def _validate_schedule_type(cls, value: str) -> str:
        """Validate schedule_type is a supported type."""
        normalized = value.strip().lower()
        try:
            ScheduleType(normalized)
        except ValueError as exc:
            allowed = [t.value for t in ScheduleType]
            msg = f"schedule_type must be one of {allowed}"
            raise ValueError(msg) from exc
        return normalized

    @field_validator("start_state")
    @classmethod
    def _validate_start_state(cls, value: str) -> str:
        """Restrict start_state to draft, active, or paused."""
        normalized = value.strip().lower()
        if normalized not in {"draft", "active", "paused"}:
            msg = "start_state must be 'draft', 'active', or 'paused'"
            raise ValueError(msg)
        return normalized

    @model_validator(mode="after")
    def _validate_definition_for_type(self) -> CreateJobRequest:
        """Validate definition fields against the declared schedule_type."""
        _validate_definition(self.schedule_type, self.definition)
        try:
            job_action_adapter.validate_python(self.job_action)
        except PydanticValidationError as exc:
            first = exc.errors()[0]
            msg = first["msg"]
            raise ValueError(f"invalid job_action: {msg}") from exc
        return self


class UpdateJobRequest(_ValidationModel):
    """Validated update-job request shape."""

    job_id: str = Field(min_length=1)
    timezone: str | None = None
    definition: dict[str, object] | None = None
    notes: str | None = None

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str | None) -> str | None:
        """Validate timezone when provided."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        try:
            ZoneInfo(normalized)
        except (KeyError, ValueError) as exc:
            msg = f"invalid timezone: {normalized}"
            raise ValueError(msg) from exc
        return normalized


class PauseJobRequest(_ValidationModel):
    """Validated pause-job request shape."""

    job_id: str = Field(min_length=1)
    reason: str = ""


class ResumeJobRequest(_ValidationModel):
    """Validated resume-job request shape."""

    job_id: str = Field(min_length=1)


class CancelJobRequest(_ValidationModel):
    """Validated cancel-job request shape."""

    job_id: str = Field(min_length=1)


class RunJobNowRequest(_ValidationModel):
    """Validated run-job-now request shape."""

    job_id: str = Field(min_length=1)


class JobIdRequest(_ValidationModel):
    """Validated request keyed by job_id."""

    job_id: str = Field(min_length=1)


class ExecutionIdRequest(_ValidationModel):
    """Validated request keyed by execution_id."""

    execution_id: str = Field(min_length=1)


class ListJobsRequest(_ValidationModel):
    """Validated list-jobs request shape."""

    state: str | None = None
    schedule_type: str | None = None
    limit: int = Field(default=50, ge=1, le=_MAX_PAGE_SIZE)
    cursor: str | None = None


class ListExecutionsRequest(_ValidationModel):
    """Validated list-executions request shape."""

    job_id: str = Field(min_length=1)
    limit: int = Field(default=50, ge=1, le=_MAX_PAGE_SIZE)
    cursor: str | None = None


class ListAuditsRequest(_ValidationModel):
    """Validated list-audits request shape."""

    job_id: str = Field(min_length=1)
    limit: int = Field(default=50, ge=1, le=_MAX_PAGE_SIZE)
    cursor: str | None = None


class ListPredicateEvaluationsRequest(_ValidationModel):
    """Validated list-predicate-evaluations request shape."""

    job_id: str = Field(min_length=1)
    limit: int = Field(default=50, ge=1, le=_MAX_PAGE_SIZE)
    cursor: str | None = None


class HandleCallbackRequest(_ValidationModel):
    """Validated provider-callback request shape."""

    job_id: str = Field(min_length=1)
    scheduled_for: datetime
    trace_id: str = Field(min_length=1)
    trigger_source: str = Field(min_length=1)


class ClaimExecutionRequest(_ValidationModel):
    """Validated claim-execution request shape."""

    worker_id: str = Field(min_length=1, default="worker")


class FailExecutionRequest(_ValidationModel):
    """Validated fail-execution request shape."""

    execution_id: str = Field(min_length=1)
    error_message: str = Field(min_length=1, max_length=2048)
    error_code: str | None = None
    is_retryable: bool = False


# ---------------------------------------------------------------------------
# Definition validation helpers
# ---------------------------------------------------------------------------


def _validate_definition(schedule_type: str, definition: dict[str, object]) -> None:
    """Validate definition fields are consistent with schedule_type.

    Raises ``ValueError`` on invalid definitions.
    """
    st = ScheduleType(schedule_type)

    if st == ScheduleType.one_time:
        _require_field(definition, "run_at", "one_time schedules require 'run_at'")

    elif st == ScheduleType.interval:
        _require_field(
            definition, "interval_count", "interval schedules require 'interval_count'"
        )
        _require_field(
            definition, "interval_unit", "interval schedules require 'interval_unit'"
        )
        count = definition.get("interval_count")
        if isinstance(count, int) and count <= 0:
            msg = "interval_count must be > 0"
            raise ValueError(msg)
        unit = definition.get("interval_unit")
        if isinstance(unit, str):
            try:
                IntervalUnit(unit)
            except ValueError as exc:
                allowed = [u.value for u in IntervalUnit]
                msg = f"interval_unit must be one of {allowed}"
                raise ValueError(msg) from exc

    elif st == ScheduleType.calendar_rule:
        _require_field(definition, "rrule", "calendar_rule schedules require 'rrule'")
        rrule_str = definition.get("rrule")
        if isinstance(rrule_str, str):
            _validate_rrule(rrule_str)

    elif st == ScheduleType.conditional:
        _require_field(
            definition,
            "predicate_op_id",
            "conditional schedules require 'predicate_op_id'",
        )
        _require_field(
            definition,
            "predicate_subject",
            "conditional schedules require 'predicate_subject'",
        )
        _require_field(
            definition,
            "predicate_operator",
            "conditional schedules require 'predicate_operator'",
        )
        _require_field(
            definition,
            "evaluation_interval_count",
            "conditional schedules require 'evaluation_interval_count'",
        )
        _require_field(
            definition,
            "evaluation_interval_unit",
            "conditional schedules require 'evaluation_interval_unit'",
        )
        op = definition.get("predicate_operator")
        if isinstance(op, str):
            try:
                PredicateOperator(op)
            except ValueError as exc:
                allowed = [o.value for o in PredicateOperator]
                msg = f"predicate_operator must be one of {allowed}"
                raise ValueError(msg) from exc
            if op != "exists" and definition.get("predicate_value") is None:
                msg = f"predicate_value is required for operator '{op}'"
                raise ValueError(msg)


def _require_field(definition: dict[str, object], field: str, message: str) -> None:
    """Raise ``ValueError`` if ``field`` is missing from ``definition``."""
    if field not in definition or definition[field] is None:
        raise ValueError(message)


def _validate_rrule(rrule: str) -> None:
    """Validate that an RRULE string contains a supported FREQ."""
    upper = rrule.upper()
    freq_found = False
    for segment in upper.split(";"):
        segment = segment.strip()
        if segment.startswith("FREQ="):
            freq_value = segment[5:].strip()
            if freq_value not in _ALLOWED_RRULE_FREQUENCIES:
                msg = (
                    f"unsupported RRULE frequency '{freq_value}'; "
                    f"allowed: {sorted(_ALLOWED_RRULE_FREQUENCIES)}"
                )
                raise ValueError(msg)
            freq_found = True
            break

    if not freq_found:
        msg = "RRULE must contain a FREQ component"
        raise ValueError(msg)
