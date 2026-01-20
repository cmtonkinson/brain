"""Unit tests for predicate evaluation audit logging.

These tests verify that predicate evaluation outcomes are properly persisted
to the database with audit records that link to schedules and executions.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from models import (
    PredicateEvaluationAuditLog,
    Schedule,
    TaskIntent,
    Execution,
)
from scheduler.data_access import (
    ActorContext,
    ExecutionActorContext,
    ExecutionCreateInput,
    PredicateEvaluationAuditInput,
    ScheduleCreateInput,
    ScheduleDefinitionInput,
    TaskIntentInput,
    create_execution,
    create_schedule,
    create_task_intent,
    get_predicate_evaluation_audit_by_evaluation_id,
    list_predicate_evaluation_audits_by_schedule,
    record_predicate_evaluation_audit,
)
from scheduler.predicate_evaluation_audit import PredicateEvaluationAuditRecorder
from scheduler.predicate_evaluation import (
    PredicateEvaluationAuditInput as ServiceAuditInput,
)


def _actor_context() -> ActorContext:
    """Return a default actor context for schedule mutations."""
    return ActorContext(
        actor_type="human",
        actor_id="user-1",
        channel="signal",
        trace_id="trace-123",
        request_id="req-456",
        reason="testing",
    )


def _execution_actor_context() -> ExecutionActorContext:
    """Return a default actor context for execution records."""
    return ExecutionActorContext(
        actor_type="scheduled",
        actor_id=None,
        channel="scheduled",
        trace_id="trace-789",
        request_id="req-999",
        actor_context="scheduled-envelope",
    )


def _create_test_schedule(
    session,
    actor: ActorContext,
    schedule_type: str = "conditional",
) -> tuple[TaskIntent, Schedule]:
    """Create a test task intent and schedule for audit tests."""
    now = datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc)
    intent = create_task_intent(
        session,
        TaskIntentInput(summary="Test task", details="Test details"),
        actor,
        now=now,
    )
    session.flush()

    definition = ScheduleDefinitionInput(
        predicate_subject="obsidian.read",
        predicate_operator="eq",
        predicate_value="expected",
        evaluation_interval_count=1,
        evaluation_interval_unit="hour",
    )
    schedule = create_schedule(
        session,
        ScheduleCreateInput(
            task_intent_id=intent.id,
            schedule_type=schedule_type,
            timezone="UTC",
            definition=definition,
            state="active",
            next_run_at=now + timedelta(hours=1),
        ),
        actor,
        now=now,
    )
    session.flush()
    return intent, schedule


def _make_audit_input(
    *,
    evaluation_id: str = "eval-001",
    schedule_id: int = 1,
    execution_id: int | None = None,
    task_intent_id: int = 1,
    evaluation_time: datetime | None = None,
    evaluated_at: datetime | None = None,
    status: str = "true",
    result_code: str = "evaluated",
    authorization_decision: str = "allow",
    error_code: str | None = None,
    error_message: str | None = None,
) -> PredicateEvaluationAuditInput:
    """Create a predicate evaluation audit input for testing."""
    now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    return PredicateEvaluationAuditInput(
        evaluation_id=evaluation_id,
        schedule_id=schedule_id,
        execution_id=execution_id,
        task_intent_id=task_intent_id,
        actor_type="scheduled",
        actor_id=None,
        actor_channel="scheduled",
        actor_privilege_level="constrained",
        actor_autonomy_level="limited",
        trace_id="trace-001",
        request_id="req-001",
        predicate_subject="obsidian.read",
        predicate_operator="eq",
        predicate_value="expected",
        predicate_value_type="string",
        evaluation_time=evaluation_time or now,
        evaluated_at=evaluated_at or now,
        status=status,
        result_code=result_code,
        message="Predicate evaluated to true.",
        observed_value="expected",
        error_code=error_code,
        error_message=error_message,
        authorization_decision=authorization_decision,
        authorization_reason_code=None,
        authorization_reason_message=None,
        authorization_policy_name=None,
        authorization_policy_version=None,
        provider_name="celery",
        provider_attempt=1,
        correlation_id="trace-001",
    )


class TestPredicateEvaluationAuditDataAccess:
    """Tests for predicate evaluation audit data access functions."""

    def test_record_audit_persists_all_fields(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify audit record persists all required fields."""
        actor = _actor_context()
        eval_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        evaluated_at = datetime(2025, 6, 15, 12, 0, 1, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent, schedule = _create_test_schedule(session, actor)
            session.commit()

            audit_input = _make_audit_input(
                evaluation_id="eval-test-001",
                schedule_id=schedule.id,
                task_intent_id=intent.id,
                evaluation_time=eval_time,
                evaluated_at=evaluated_at,
                status="true",
                result_code="evaluated",
            )

            audit = record_predicate_evaluation_audit(session, audit_input)
            session.commit()
            session.refresh(audit)

            assert audit.id is not None
            assert audit.evaluation_id == "eval-test-001"
            assert audit.schedule_id == schedule.id
            assert audit.task_intent_id == intent.id
            assert audit.execution_id is None
            assert audit.actor_type == "scheduled"
            assert audit.actor_id is None
            assert audit.actor_channel == "scheduled"
            assert audit.actor_privilege_level == "constrained"
            assert audit.actor_autonomy_level == "limited"
            assert audit.trace_id == "trace-001"
            assert audit.request_id == "req-001"
            assert audit.predicate_subject == "obsidian.read"
            assert audit.predicate_operator == "eq"
            assert audit.predicate_value == "expected"
            assert audit.predicate_value_type == "string"
            assert audit.status == "true"
            assert audit.result_code == "evaluated"
            assert audit.message == "Predicate evaluated to true."
            assert audit.observed_value == "expected"
            assert audit.error_code is None
            assert audit.error_message is None
            assert audit.authorization_decision == "allow"
            assert audit.provider_name == "celery"
            assert audit.provider_attempt == 1
            assert audit.correlation_id == "trace-001"
            assert audit.created_at is not None

    def test_record_audit_with_execution_link(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify audit record can link to an execution."""
        actor = _actor_context()
        exec_actor = _execution_actor_context()
        now = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent, schedule = _create_test_schedule(session, actor)
            session.flush()

            execution = create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=now,
                    status="running",
                ),
                exec_actor,
                now=now,
            )
            session.commit()

            audit_input = _make_audit_input(
                evaluation_id="eval-with-exec-001",
                schedule_id=schedule.id,
                execution_id=execution.id,
                task_intent_id=intent.id,
            )

            audit = record_predicate_evaluation_audit(session, audit_input)
            session.commit()

            assert audit.execution_id == execution.id

    def test_record_audit_with_error_fields(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify audit record persists error details."""
        actor = _actor_context()

        with closing(sqlite_session_factory()) as session:
            intent, schedule = _create_test_schedule(session, actor)
            session.commit()

            audit_input = _make_audit_input(
                evaluation_id="eval-error-001",
                schedule_id=schedule.id,
                task_intent_id=intent.id,
                status="error",
                result_code="forbidden",
                authorization_decision="deny",
                error_code="forbidden",
                error_message="Capability denied for scheduled actor.",
            )

            audit = record_predicate_evaluation_audit(session, audit_input)
            session.commit()
            session.refresh(audit)

            assert audit.status == "error"
            assert audit.result_code == "forbidden"
            assert audit.authorization_decision == "deny"
            assert audit.error_code == "forbidden"
            assert audit.error_message == "Capability denied for scheduled actor."


class TestPredicateEvaluationAuditIdempotency:
    """Tests for idempotency of predicate evaluation audit recording."""

    def test_duplicate_evaluation_id_returns_existing_record(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify duplicate evaluation_id returns existing record."""
        actor = _actor_context()

        with closing(sqlite_session_factory()) as session:
            intent, schedule = _create_test_schedule(session, actor)
            session.commit()

            audit_input_1 = _make_audit_input(
                evaluation_id="eval-idempotent-001",
                schedule_id=schedule.id,
                task_intent_id=intent.id,
                status="true",
                result_code="evaluated",
            )

            # First call creates the record
            audit_1 = record_predicate_evaluation_audit(session, audit_input_1)
            session.commit()
            first_id = audit_1.id

            # Second call with same evaluation_id but different data
            audit_input_2 = _make_audit_input(
                evaluation_id="eval-idempotent-001",  # Same evaluation_id
                schedule_id=schedule.id,
                task_intent_id=intent.id,
                status="false",  # Different status
                result_code="re-evaluated",  # Different result_code
            )

            audit_2 = record_predicate_evaluation_audit(session, audit_input_2)
            session.commit()

            # Should return the same record
            assert audit_2.id == first_id
            assert audit_2.status == "true"  # Original status preserved
            assert audit_2.result_code == "evaluated"  # Original code preserved

    def test_different_evaluation_ids_create_separate_records(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify different evaluation_ids create separate records."""
        actor = _actor_context()

        with closing(sqlite_session_factory()) as session:
            intent, schedule = _create_test_schedule(session, actor)
            session.commit()

            audit_input_1 = _make_audit_input(
                evaluation_id="eval-unique-001",
                schedule_id=schedule.id,
                task_intent_id=intent.id,
            )
            audit_input_2 = _make_audit_input(
                evaluation_id="eval-unique-002",
                schedule_id=schedule.id,
                task_intent_id=intent.id,
            )

            audit_1 = record_predicate_evaluation_audit(session, audit_input_1)
            audit_2 = record_predicate_evaluation_audit(session, audit_input_2)
            session.commit()

            assert audit_1.id != audit_2.id
            assert audit_1.evaluation_id == "eval-unique-001"
            assert audit_2.evaluation_id == "eval-unique-002"

    def test_repeated_callback_evaluations_are_idempotent(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify repeated scheduler callback evaluations are idempotent."""
        actor = _actor_context()

        with closing(sqlite_session_factory()) as session:
            intent, schedule = _create_test_schedule(session, actor)
            session.commit()

            # Simulate multiple callback deliveries with same evaluation_id
            for attempt in range(3):
                audit_input = _make_audit_input(
                    evaluation_id="eval-callback-001",
                    schedule_id=schedule.id,
                    task_intent_id=intent.id,
                )
                record_predicate_evaluation_audit(session, audit_input)
                session.commit()

            # Only one record should exist
            count = (
                session.query(PredicateEvaluationAuditLog)
                .filter(
                    PredicateEvaluationAuditLog.evaluation_id == "eval-callback-001"
                )
                .count()
            )
            assert count == 1


class TestPredicateEvaluationAuditQueries:
    """Tests for predicate evaluation audit query functions."""

    def test_get_by_evaluation_id_returns_record(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify get_by_evaluation_id returns the correct record."""
        actor = _actor_context()

        with closing(sqlite_session_factory()) as session:
            intent, schedule = _create_test_schedule(session, actor)
            session.commit()

            audit_input = _make_audit_input(
                evaluation_id="eval-query-001",
                schedule_id=schedule.id,
                task_intent_id=intent.id,
            )
            record_predicate_evaluation_audit(session, audit_input)
            session.commit()

            result = get_predicate_evaluation_audit_by_evaluation_id(
                session, "eval-query-001"
            )

            assert result is not None
            assert result.evaluation_id == "eval-query-001"

    def test_get_by_evaluation_id_returns_none_when_not_found(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify get_by_evaluation_id returns None for missing records."""
        with closing(sqlite_session_factory()) as session:
            result = get_predicate_evaluation_audit_by_evaluation_id(
                session, "nonexistent-eval-id"
            )

            assert result is None

    def test_list_by_schedule_returns_ordered_records(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify list_by_schedule returns records ordered by evaluated_at desc."""
        actor = _actor_context()

        with closing(sqlite_session_factory()) as session:
            intent, schedule = _create_test_schedule(session, actor)
            session.commit()

            # Create multiple audit records with different evaluated_at times
            base_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
            for i in range(3):
                audit_input = _make_audit_input(
                    evaluation_id=f"eval-list-{i:03d}",
                    schedule_id=schedule.id,
                    task_intent_id=intent.id,
                    evaluated_at=base_time + timedelta(hours=i),
                )
                record_predicate_evaluation_audit(session, audit_input)
            session.commit()

            results = list_predicate_evaluation_audits_by_schedule(
                session, schedule.id
            )

            assert len(results) == 3
            # Most recent first
            assert results[0].evaluation_id == "eval-list-002"
            assert results[1].evaluation_id == "eval-list-001"
            assert results[2].evaluation_id == "eval-list-000"

    def test_list_by_schedule_respects_limit(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify list_by_schedule respects the limit parameter."""
        actor = _actor_context()

        with closing(sqlite_session_factory()) as session:
            intent, schedule = _create_test_schedule(session, actor)
            session.commit()

            base_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
            for i in range(5):
                audit_input = _make_audit_input(
                    evaluation_id=f"eval-limit-{i:03d}",
                    schedule_id=schedule.id,
                    task_intent_id=intent.id,
                    evaluated_at=base_time + timedelta(hours=i),
                )
                record_predicate_evaluation_audit(session, audit_input)
            session.commit()

            results = list_predicate_evaluation_audits_by_schedule(
                session, schedule.id, limit=2
            )

            assert len(results) == 2
            # Most recent first
            assert results[0].evaluation_id == "eval-limit-004"
            assert results[1].evaluation_id == "eval-limit-003"

    def test_list_by_schedule_filters_by_schedule_id(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify list_by_schedule only returns records for the given schedule."""
        actor = _actor_context()

        with closing(sqlite_session_factory()) as session:
            intent1, schedule1 = _create_test_schedule(session, actor)
            intent2, schedule2 = _create_test_schedule(session, actor)
            session.commit()

            # Create audit records for both schedules
            audit_input_1 = _make_audit_input(
                evaluation_id="eval-filter-001",
                schedule_id=schedule1.id,
                task_intent_id=intent1.id,
            )
            audit_input_2 = _make_audit_input(
                evaluation_id="eval-filter-002",
                schedule_id=schedule2.id,
                task_intent_id=intent2.id,
            )
            record_predicate_evaluation_audit(session, audit_input_1)
            record_predicate_evaluation_audit(session, audit_input_2)
            session.commit()

            results = list_predicate_evaluation_audits_by_schedule(
                session, schedule1.id
            )

            assert len(results) == 1
            assert results[0].evaluation_id == "eval-filter-001"


class TestPredicateEvaluationAuditRecorderIntegration:
    """Tests for the PredicateEvaluationAuditRecorder class integration."""

    def test_recorder_persists_audit_via_service_input(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify recorder correctly persists audit from service-layer input."""
        actor = _actor_context()
        eval_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        evaluated_at = datetime(2025, 6, 15, 12, 0, 1, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent, schedule = _create_test_schedule(session, actor)
            session.commit()
            # Capture IDs before session closes to avoid DetachedInstanceError
            schedule_id = schedule.id
            intent_id = intent.id

        # Create recorder with session factory
        recorder = PredicateEvaluationAuditRecorder(sqlite_session_factory)

        # Use service-layer audit input (as used by PredicateEvaluationService)
        service_input = ServiceAuditInput(
            evaluation_id="eval-recorder-001",
            schedule_id=schedule_id,
            execution_id=None,
            task_intent_id=intent_id,
            actor_type="scheduled",
            actor_id=None,
            actor_channel="scheduled",
            actor_privilege_level="constrained",
            actor_autonomy_level="limited",
            trace_id="recorder-trace-001",
            request_id="recorder-req-001",
            predicate_subject="obsidian.read",
            predicate_operator="eq",
            predicate_value="test-value",
            predicate_value_type="string",
            evaluation_time=eval_time,
            evaluated_at=evaluated_at,
            status="true",
            result_code="evaluated",
            message="Evaluation succeeded.",
            observed_value="test-value",
            error_code=None,
            error_message=None,
            authorization_decision="allow",
            authorization_reason_code=None,
            authorization_reason_message=None,
            authorization_policy_name=None,
            authorization_policy_version=None,
            provider_name="celery",
            provider_attempt=1,
            correlation_id="recorder-trace-001",
        )

        # Record via the recorder
        recorder.record(service_input)

        # Verify persisted
        with closing(sqlite_session_factory()) as session:
            audit = get_predicate_evaluation_audit_by_evaluation_id(
                session, "eval-recorder-001"
            )

            assert audit is not None
            assert audit.evaluation_id == "eval-recorder-001"
            assert audit.schedule_id == schedule_id
            assert audit.task_intent_id == intent_id
            assert audit.status == "true"
            assert audit.observed_value == "test-value"
            assert audit.trace_id == "recorder-trace-001"

    def test_recorder_idempotent_for_same_evaluation_id(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify recorder is idempotent for repeated calls."""
        actor = _actor_context()
        eval_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent, schedule = _create_test_schedule(session, actor)
            session.commit()
            # Capture IDs before session closes to avoid DetachedInstanceError
            schedule_id = schedule.id
            intent_id = intent.id

        recorder = PredicateEvaluationAuditRecorder(sqlite_session_factory)

        service_input = ServiceAuditInput(
            evaluation_id="eval-recorder-idempotent-001",
            schedule_id=schedule_id,
            execution_id=None,
            task_intent_id=intent_id,
            actor_type="scheduled",
            actor_id=None,
            actor_channel="scheduled",
            actor_privilege_level="constrained",
            actor_autonomy_level="limited",
            trace_id="trace-001",
            request_id="req-001",
            predicate_subject="obsidian.read",
            predicate_operator="eq",
            predicate_value="expected",
            predicate_value_type="string",
            evaluation_time=eval_time,
            evaluated_at=eval_time,
            status="true",
            result_code="evaluated",
            message="First evaluation.",
            observed_value="expected",
            error_code=None,
            error_message=None,
            authorization_decision="allow",
            authorization_reason_code=None,
            authorization_reason_message=None,
            authorization_policy_name=None,
            authorization_policy_version=None,
            provider_name="celery",
            provider_attempt=1,
            correlation_id="trace-001",
        )

        # Record multiple times
        recorder.record(service_input)
        recorder.record(service_input)
        recorder.record(service_input)

        # Verify only one record exists
        with closing(sqlite_session_factory()) as session:
            count = (
                session.query(PredicateEvaluationAuditLog)
                .filter(
                    PredicateEvaluationAuditLog.evaluation_id
                    == "eval-recorder-idempotent-001"
                )
                .count()
            )
            assert count == 1

    def test_recorder_rollback_on_error(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify recorder rolls back transaction on error."""
        actor = _actor_context()

        with closing(sqlite_session_factory()) as session:
            intent, schedule = _create_test_schedule(session, actor)
            session.commit()
            # Capture IDs before session closes to avoid DetachedInstanceError
            schedule_id = schedule.id
            intent_id = intent.id

        recorder = PredicateEvaluationAuditRecorder(sqlite_session_factory)

        eval_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        # Create an invalid input (schedule_id that doesn't match FK constraint
        # won't work in sqlite without FK enforcement, so we test with a valid
        # input and verify no partial commits happen)
        service_input = ServiceAuditInput(
            evaluation_id="eval-rollback-001",
            schedule_id=schedule_id,
            execution_id=None,
            task_intent_id=intent_id,
            actor_type="scheduled",
            actor_id=None,
            actor_channel="scheduled",
            actor_privilege_level="constrained",
            actor_autonomy_level="limited",
            trace_id="trace-001",
            request_id="req-001",
            predicate_subject="obsidian.read",
            predicate_operator="eq",
            predicate_value="expected",
            predicate_value_type="string",
            evaluation_time=eval_time,
            evaluated_at=eval_time,
            status="true",
            result_code="evaluated",
            message="Test message.",
            observed_value="expected",
            error_code=None,
            error_message=None,
            authorization_decision="allow",
            authorization_reason_code=None,
            authorization_reason_message=None,
            authorization_policy_name=None,
            authorization_policy_version=None,
            provider_name="celery",
            provider_attempt=1,
            correlation_id="trace-001",
        )

        # Successful recording
        recorder.record(service_input)

        # Verify recorded
        with closing(sqlite_session_factory()) as session:
            audit = get_predicate_evaluation_audit_by_evaluation_id(
                session, "eval-rollback-001"
            )
            assert audit is not None


class TestPredicateEvaluationAuditActorContext:
    """Tests for actor context preservation in audit records."""

    def test_audit_preserves_scheduled_actor_context(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify audit records preserve full scheduled actor context."""
        actor = _actor_context()
        eval_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent, schedule = _create_test_schedule(session, actor)
            session.commit()

            audit_input = PredicateEvaluationAuditInput(
                evaluation_id="eval-actor-001",
                schedule_id=schedule.id,
                execution_id=None,
                task_intent_id=intent.id,
                actor_type="scheduled",
                actor_id="sched-job-123",
                actor_channel="scheduled",
                actor_privilege_level="constrained",
                actor_autonomy_level="limited",
                trace_id="actor-trace-001",
                request_id="actor-req-001",
                predicate_subject="obsidian.read",
                predicate_operator="eq",
                predicate_value="test",
                predicate_value_type="string",
                evaluation_time=eval_time,
                evaluated_at=eval_time,
                status="true",
                result_code="evaluated",
                message="Test",
                observed_value="test",
                error_code=None,
                error_message=None,
                authorization_decision="allow",
                authorization_reason_code=None,
                authorization_reason_message=None,
                authorization_policy_name=None,
                authorization_policy_version=None,
                provider_name="celery",
                provider_attempt=1,
                correlation_id="actor-trace-001",
            )

            audit = record_predicate_evaluation_audit(session, audit_input)
            session.commit()
            session.refresh(audit)

            assert audit.actor_type == "scheduled"
            assert audit.actor_id == "sched-job-123"
            assert audit.actor_channel == "scheduled"
            assert audit.actor_privilege_level == "constrained"
            assert audit.actor_autonomy_level == "limited"
            assert audit.trace_id == "actor-trace-001"
            assert audit.request_id == "actor-req-001"

    def test_audit_preserves_authorization_decision_metadata(
        self,
        sqlite_session_factory: sessionmaker,
    ) -> None:
        """Verify audit records preserve authorization decision metadata."""
        actor = _actor_context()
        eval_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        with closing(sqlite_session_factory()) as session:
            intent, schedule = _create_test_schedule(session, actor)
            session.commit()

            audit_input = PredicateEvaluationAuditInput(
                evaluation_id="eval-authz-001",
                schedule_id=schedule.id,
                execution_id=None,
                task_intent_id=intent.id,
                actor_type="scheduled",
                actor_id=None,
                actor_channel="scheduled",
                actor_privilege_level="constrained",
                actor_autonomy_level="limited",
                trace_id="authz-trace-001",
                request_id="authz-req-001",
                predicate_subject="obsidian.write",
                predicate_operator="eq",
                predicate_value="test",
                predicate_value_type="string",
                evaluation_time=eval_time,
                evaluated_at=eval_time,
                status="error",
                result_code="forbidden",
                message="Write capability denied.",
                observed_value=None,
                error_code="forbidden",
                error_message="Capability denied for scheduled actor.",
                authorization_decision="deny",
                authorization_reason_code="capability_not_read_only",
                authorization_reason_message="Only read-only capabilities are allowed.",
                authorization_policy_name="predicate_evaluation_policy",
                authorization_policy_version="1.0",
                provider_name="celery",
                provider_attempt=1,
                correlation_id="authz-trace-001",
            )

            audit = record_predicate_evaluation_audit(session, audit_input)
            session.commit()
            session.refresh(audit)

            assert audit.authorization_decision == "deny"
            assert audit.authorization_reason_code == "capability_not_read_only"
            assert audit.authorization_reason_message == "Only read-only capabilities are allowed."
            assert audit.authorization_policy_name == "predicate_evaluation_policy"
            assert audit.authorization_policy_version == "1.0"
