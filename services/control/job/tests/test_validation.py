"""Tests for Job Service request validation models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.control.job.validation import (
    CreateJobRequest,
    HandleCallbackRequest,
    UpdateJobRequest,
    _validate_rrule,
)


class TestCreateJobRequest:
    """Validation for create-job requests."""

    def test_valid_one_time(self) -> None:
        r = CreateJobRequest(
            summary="test",
            schedule_type="one_time",
            timezone="UTC",
            definition={"run_at": "2026-06-01T00:00:00Z"},
            job_action={
                "type": "capability_invocation",
                "capability_id": "demo-capability",
            },
        )
        assert r.schedule_type == "one_time"
        assert r.start_state == "draft"

    def test_valid_interval(self) -> None:
        r = CreateJobRequest(
            summary="test",
            schedule_type="interval",
            timezone="America/New_York",
            definition={"interval_count": 5, "interval_unit": "hour"},
            job_action={
                "type": "capability_invocation",
                "capability_id": "demo-capability",
            },
        )
        assert r.schedule_type == "interval"

    def test_valid_calendar_rule(self) -> None:
        r = CreateJobRequest(
            summary="test",
            schedule_type="calendar_rule",
            timezone="UTC",
            definition={"rrule": "FREQ=DAILY;INTERVAL=1"},
            job_action={
                "type": "capability_invocation",
                "capability_id": "demo-capability",
            },
        )
        assert r.schedule_type == "calendar_rule"

    def test_valid_conditional(self) -> None:
        r = CreateJobRequest(
            summary="test",
            schedule_type="conditional",
            timezone="UTC",
            definition={
                "predicate_subject": "vault.read/status",
                "predicate_capability_id": "predicate-read",
                "predicate_operator": "eq",
                "predicate_value": "ready",
                "evaluation_interval_count": 10,
                "evaluation_interval_unit": "minute",
            },
            job_action={
                "type": "capability_invocation",
                "capability_id": "demo-capability",
            },
        )
        assert r.schedule_type == "conditional"

    def test_invalid_timezone(self) -> None:
        with pytest.raises(ValidationError, match="invalid timezone"):
            CreateJobRequest(
                summary="test",
                schedule_type="one_time",
                timezone="Not/A/Zone",
                definition={"run_at": "2026-06-01T00:00:00Z"},
                job_action={
                    "type": "capability_invocation",
                    "capability_id": "demo-capability",
                },
            )

    def test_invalid_schedule_type(self) -> None:
        with pytest.raises(ValidationError, match="schedule_type must be"):
            CreateJobRequest(
                summary="test",
                schedule_type="bogus",
                timezone="UTC",
                definition={},
                job_action={
                    "type": "capability_invocation",
                    "capability_id": "demo-capability",
                },
            )

    def test_invalid_start_state(self) -> None:
        with pytest.raises(ValidationError, match="start_state must be"):
            CreateJobRequest(
                summary="test",
                schedule_type="one_time",
                timezone="UTC",
                definition={"run_at": "2026-06-01T00:00:00Z"},
                job_action={
                    "type": "capability_invocation",
                    "capability_id": "demo-capability",
                },
                start_state="paused",
            )

    def test_empty_summary_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateJobRequest(
                summary="",
                schedule_type="one_time",
                timezone="UTC",
                definition={"run_at": "2026-06-01T00:00:00Z"},
                job_action={
                    "type": "capability_invocation",
                    "capability_id": "demo-capability",
                },
            )

    def test_one_time_requires_run_at(self) -> None:
        with pytest.raises(ValidationError, match="run_at"):
            CreateJobRequest(
                summary="test",
                schedule_type="one_time",
                timezone="UTC",
                definition={},
                job_action={
                    "type": "capability_invocation",
                    "capability_id": "demo-capability",
                },
            )

    def test_interval_requires_count_and_unit(self) -> None:
        with pytest.raises(ValidationError, match="interval_count"):
            CreateJobRequest(
                summary="test",
                schedule_type="interval",
                timezone="UTC",
                definition={"interval_unit": "hour"},
                job_action={
                    "type": "capability_invocation",
                    "capability_id": "demo-capability",
                },
            )

    def test_calendar_rule_requires_rrule(self) -> None:
        with pytest.raises(ValidationError, match="rrule"):
            CreateJobRequest(
                summary="test",
                schedule_type="calendar_rule",
                timezone="UTC",
                definition={},
                job_action={
                    "type": "capability_invocation",
                    "capability_id": "demo-capability",
                },
            )

    def test_conditional_requires_predicate(self) -> None:
        with pytest.raises(ValidationError, match="predicate_subject"):
            CreateJobRequest(
                summary="test",
                schedule_type="conditional",
                timezone="UTC",
                definition={
                    "predicate_capability_id": "predicate-read",
                    "evaluation_interval_count": 10,
                    "evaluation_interval_unit": "minute",
                },
                job_action={
                    "type": "capability_invocation",
                    "capability_id": "demo-capability",
                },
            )

    def test_conditional_requires_value_for_comparison(self) -> None:
        with pytest.raises(ValidationError, match="predicate_value"):
            CreateJobRequest(
                summary="test",
                schedule_type="conditional",
                timezone="UTC",
                definition={
                    "predicate_capability_id": "predicate-read",
                    "predicate_subject": "x",
                    "predicate_operator": "eq",
                    "evaluation_interval_count": 1,
                    "evaluation_interval_unit": "hour",
                },
                job_action={
                    "type": "capability_invocation",
                    "capability_id": "demo-capability",
                },
            )

    def test_invalid_job_action(self) -> None:
        with pytest.raises(ValidationError, match="invalid job_action"):
            CreateJobRequest(
                summary="test",
                schedule_type="one_time",
                timezone="UTC",
                definition={"run_at": "2026-06-01T00:00:00Z"},
                job_action={"type": "capability_invocation"},
            )


class TestRruleValidation:
    """Validation of RRULE strings."""

    def test_valid_daily(self) -> None:
        _validate_rrule("FREQ=DAILY;INTERVAL=1")

    def test_valid_weekly(self) -> None:
        _validate_rrule("FREQ=WEEKLY;BYDAY=MO,WE,FR")

    def test_rejects_unsupported_freq(self) -> None:
        with pytest.raises(ValueError, match="unsupported RRULE frequency"):
            _validate_rrule("FREQ=SECONDLY")

    def test_rejects_missing_freq(self) -> None:
        with pytest.raises(ValueError, match="RRULE must contain a FREQ"):
            _validate_rrule("INTERVAL=1;BYDAY=MO")


class TestUpdateJobRequest:
    """Validation for update-job requests."""

    def test_valid_partial(self) -> None:
        r = UpdateJobRequest(job_id="abc123", timezone="UTC")
        assert r.timezone == "UTC"
        assert r.definition is None

    def test_invalid_timezone(self) -> None:
        with pytest.raises(ValidationError, match="invalid timezone"):
            UpdateJobRequest(job_id="abc123", timezone="Nope/Zone")

    def test_empty_job_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UpdateJobRequest(job_id="")


class TestHandleCallbackRequest:
    """Validation for callback requests."""

    def test_valid(self) -> None:
        r = HandleCallbackRequest(
            job_id="abc123",
            scheduled_for="2026-06-01T00:00:00Z",
            trace_id="trace-1",
            trigger_source="scheduled",
        )
        assert r.trace_id == "trace-1"

    def test_empty_trace_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            HandleCallbackRequest(
                job_id="abc123",
                scheduled_for="2026-06-01T00:00:00Z",
                trace_id="",
                trigger_source="scheduled",
            )

    def test_empty_trigger_source_rejected(self) -> None:
        with pytest.raises(ValidationError):
            HandleCallbackRequest(
                job_id="abc123",
                scheduled_for="2026-06-01T00:00:00Z",
                trace_id="trace-1",
                trigger_source="",
            )
