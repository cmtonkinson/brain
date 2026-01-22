"""End-to-end coverage for all schedule types through the command service."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Callable

import pytest
from sqlalchemy.orm import sessionmaker

from models import PredicateEvaluationAuditLog, Schedule, ScheduleAuditLog
from scheduler.adapter_interface import AdapterHealth, SchedulePayload, SchedulerAdapter
from scheduler.predicate_evaluation import PredicateEvaluationService, PredicateEvaluationStatus
from scheduler.predicate_evaluation_audit import PredicateEvaluationAuditRecorder
from scheduler.schedule_service import ScheduleCommandServiceImpl
from scheduler.schedule_service_interface import (
    ActorContext,
    ScheduleCreateRequest,
    ScheduleDefinitionInput,
    ScheduleValidationError,
    TaskIntentInput,
)


class _RecordingAdapter(SchedulerAdapter):
    """Stub scheduler adapter that records lifecycle calls."""

    def __init__(self) -> None:
        """Initialize stub storage."""
        self.registered: list[SchedulePayload] = []
        self.updated: list[SchedulePayload] = []
        self.paused: list[int] = []
        self.resumed: list[int] = []
        self.deleted: list[int] = []
        self.triggered: list[tuple[int, datetime, str | None, str]] = []

    def register_schedule(self, payload: SchedulePayload) -> None:
        """Record schedule registrations."""
        self.registered.append(payload)

    def update_schedule(self, payload: SchedulePayload) -> None:
        """Record schedule updates."""
        self.updated.append(payload)

    def pause_schedule(self, schedule_id: int) -> None:
        """Record schedule pauses."""
        self.paused.append(schedule_id)

    def resume_schedule(self, schedule_id: int) -> None:
        """Record scheduler resumes."""
        self.resumed.append(schedule_id)

    def delete_schedule(self, schedule_id: int) -> None:
        """Record schedule deletions."""
        self.deleted.append(schedule_id)

    def trigger_callback(
        self,
        schedule_id: int,
        scheduled_for: datetime,
        *,
        trace_id: str | None = None,
        trigger_source: str = "scheduler_callback",
    ) -> None:
        """Record run-now triggers along with their origin."""
        self.triggered.append((schedule_id, scheduled_for, trace_id, trigger_source))

    def check_health(self) -> AdapterHealth:
        """Return a healthy stub status."""
        return AdapterHealth(status="ok", message="stub adapter ready")


class _StaticSubjectResolver:
    """Simple resolver that returns pre-defined values for subjects."""

    def __init__(self, values: dict[str, str | int | float | bool | None]) -> None:
        """Initialize the resolver with a mapping."""
        self._values = values

    def resolve(
        self,
        subject: str,
        actor_context: object,
    ) -> str | int | float | bool | None:
        """Return the mapped value for the subject (or None if missing)."""
        return self._values.get(subject)


def _actor_context() -> ActorContext:
    """Return a default actor context used across tests."""
    return ActorContext(
        actor_type="integration",
        actor_id="schedule-types",
        channel="signal",
        trace_id="trace-schedule-types",
        request_id="req-schedule-types",
        reason="integration-test",
    )


def _build_service(
    sqlite_session_factory: sessionmaker,
    now: datetime,
) -> tuple[_RecordingAdapter, ScheduleCommandServiceImpl, ActorContext]:
    """Construct the schedule command service stack with a deterministic clock."""
    adapter = _RecordingAdapter()
    service = ScheduleCommandServiceImpl(
        sqlite_session_factory,
        adapter,
        now_provider=lambda: now,
    )
    return adapter, service, _actor_context()


@pytest.mark.parametrize(
    (
        "schedule_type",
        "definition_builder",
        "assert_field",
    ),
    [
        (
            "one_time",
            lambda now: ScheduleDefinitionInput(run_at=now + timedelta(minutes=5)),
            "run_at",
        ),
        (
            "interval",
            lambda _: ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            "interval_count",
        ),
        (
            "calendar_rule",
            lambda _: ScheduleDefinitionInput(rrule="FREQ=DAILY;BYHOUR=7"),
            "rrule",
        ),
        (
            "conditional",
            lambda _: ScheduleDefinitionInput(
                predicate_subject="vault.search/documents",
                predicate_operator="exists",
                evaluation_interval_count=5,
                evaluation_interval_unit="minute",
            ),
            "predicate_subject",
        ),
    ],
    ids=["one_time", "interval", "calendar_rule", "conditional"],
)
def test_schedule_type_creation_records_audit_and_state(
    sqlite_session_factory: sessionmaker,
    schedule_type: str,
    definition_builder: Callable[[datetime], ScheduleDefinitionInput],
    assert_field: str,
) -> None:
    """Ensure every schedule type creates valid records and audits."""
    now = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    adapter, service, actor = _build_service(sqlite_session_factory, now)
    definition = definition_builder(now)

    request = ScheduleCreateRequest(
        task_intent=TaskIntentInput(
            summary=f"{schedule_type.capitalize()} coverage",
            details="Verify audit and definition storage.",
        ),
        schedule_type=schedule_type,
        timezone="UTC",
        definition=definition,
    )

    result = service.create_schedule(request, actor)

    assert result.schedule.schedule_type == schedule_type
    assert result.audit_log_id is not None

    with closing(sqlite_session_factory()) as session:
        stored = session.query(Schedule).filter_by(id=result.schedule.id).one()
        audit = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=result.schedule.id, event_type="create")
            .one()
        )

    assert audit.id == result.audit_log_id
    assert audit.event_type == "create"
    assert result.schedule.id == stored.id
    assert len(adapter.registered) == 1
    assert adapter.registered[0].schedule_id == stored.id
    assert getattr(stored, assert_field) is not None

    if schedule_type == "conditional":
        evaluation_id = f"eval-{result.schedule.id}"
        evaluation_time = now + timedelta(minutes=1)
        resolver = _StaticSubjectResolver({"vault.search/documents": "available"})
        evaluation_service = PredicateEvaluationService(
            session_factory=sqlite_session_factory,
            subject_resolver=resolver,
            audit_recorder=PredicateEvaluationAuditRecorder(sqlite_session_factory),
            now_provider=lambda: evaluation_time,
        )
        evaluation_result = evaluation_service.evaluate_schedule(
            schedule_id=result.schedule.id,
            evaluation_id=evaluation_id,
            evaluation_time=evaluation_time,
            provider_name="test-scheduler",
            provider_attempt=1,
            trace_id="trace-conditional-eval",
        )
        assert evaluation_result.status == PredicateEvaluationStatus.TRUE

        with closing(sqlite_session_factory()) as session:
            predicate_audit = (
                session.query(PredicateEvaluationAuditLog)
                .filter_by(schedule_id=result.schedule.id, evaluation_id=evaluation_id)
                .one()
            )
        assert predicate_audit.evaluation_id == evaluation_id
        assert str(predicate_audit.status) == "true"


@pytest.mark.parametrize(
    (
        "schedule_type",
        "definition",
        "expected_field",
    ),
    [
        ("one_time", ScheduleDefinitionInput(), "run_at"),
        (
            "interval",
            ScheduleDefinitionInput(interval_count=0, interval_unit="minute"),
            "interval_count",
        ),
        ("calendar_rule", ScheduleDefinitionInput(rrule="FREQ=UNKNOWN"), "rrule"),
        (
            "conditional",
            ScheduleDefinitionInput(
                predicate_subject=None,
                predicate_operator="exists",
                evaluation_interval_count=5,
                evaluation_interval_unit="minute",
            ),
            "predicate_subject",
        ),
    ],
    ids=[
        "one_time_missing_run_at",
        "interval_invalid_count",
        "calendar_rule_invalid_freq",
        "conditional_missing_subject",
    ],
)
def test_schedule_type_validation_errors(
    sqlite_session_factory: sessionmaker,
    schedule_type: str,
    definition: ScheduleDefinitionInput,
    expected_field: str,
) -> None:
    """Verify invalid definitions raise validation errors without registering schedules."""
    now = datetime(2025, 2, 2, 8, 0, tzinfo=timezone.utc)
    adapter, service, actor = _build_service(sqlite_session_factory, now)

    request = ScheduleCreateRequest(
        task_intent=TaskIntentInput(
            summary="Invalid cadence",
            details="Force validation failure.",
        ),
        schedule_type=schedule_type,
        timezone="UTC",
        definition=definition,
    )

    with pytest.raises(ScheduleValidationError) as excinfo:
        service.create_schedule(request, actor)

    assert excinfo.value.details.get("field") == expected_field
    assert len(adapter.registered) == 0
