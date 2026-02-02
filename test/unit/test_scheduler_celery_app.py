"""Unit tests for the scheduler Celery evaluate_predicate helper."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy.orm import sessionmaker

from ingestion.stages.extract import Stage2ExtractionResult

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import scheduler.celery_app as celery_app
from scheduler import data_access
from scheduler.celery_app import (
    evaluate_conditional_schedule,
    process_due_retry_executions,
)
from scheduler.predicate_evaluation import (
    PredicateEvaluationError,
    PredicateEvaluationResult,
    PredicateEvaluationStatus,
)
from models import Schedule


class _StubEvaluationService:
    """Simplified evaluation service stub for testing helper logic."""

    def __init__(self, result: PredicateEvaluationResult) -> None:
        self.result = result
        self.calls: list[tuple[int, str, datetime, str, int, str]] = []

    def evaluate_schedule(
        self,
        schedule_id: int,
        *,
        evaluation_id: str,
        evaluation_time: datetime,
        provider_name: str,
        provider_attempt: int,
        trace_id: str,
    ) -> PredicateEvaluationResult:
        """Capture invocation parameters and return the configured result."""
        self.calls.append(
            (
                schedule_id,
                evaluation_id,
                evaluation_time,
                provider_name,
                provider_attempt,
                trace_id,
            )
        )
        return self.result


def _make_result(
    status: PredicateEvaluationStatus,
    *,
    message: str | None = None,
    error: PredicateEvaluationError | None = None,
) -> PredicateEvaluationResult:
    """Produce a minimal PredicateEvaluationResult for testing."""
    return PredicateEvaluationResult(
        status=status,
        result_code="test",
        message=message,
        observed_value="value",
        evaluated_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        error=error,
    )


def test_evaluate_conditional_schedule_dispatches_on_true() -> None:
    """A true predicate should persist metadata and trigger dispatch."""
    evaluation_time = datetime(2025, 1, 1, 12, 30, tzinfo=timezone.utc)
    result = _make_result(PredicateEvaluationStatus.TRUE, message="match")
    service = _StubEvaluationService(result)
    persisted: list[tuple[int, datetime, PredicateEvaluationResult]] = []

    def persistor(schedule_id: int, time: datetime, payload: PredicateEvaluationResult) -> None:
        persisted.append((schedule_id, time, payload))

    dispatched: list[tuple[int, datetime]] = []

    def dispatcher(schedule_id: int, scheduled_for: datetime) -> bool:
        dispatched.append((schedule_id, scheduled_for))
        return True

    response = evaluate_conditional_schedule(
        42,
        evaluation_time,
        evaluation_service_factory=lambda: service,
        metadata_persistor=persistor,
        dispatcher_trigger=dispatcher,
        provider_name="test.provider",
        provider_attempt=2,
        trace_id="trace-1",
        evaluation_id="eval-1",
    )

    assert response["status"] == PredicateEvaluationStatus.TRUE
    assert response["execution_dispatched"] is True
    assert persisted == [(42, evaluation_time, result)]
    assert dispatched == [(42, evaluation_time)]
    assert service.calls[0][3] == "test.provider"


def test_evaluate_conditional_schedule_skips_dispatch_on_false() -> None:
    """False evaluations should not trigger executions."""
    result = _make_result(PredicateEvaluationStatus.FALSE)
    service = _StubEvaluationService(result)
    dispatched: list[int] = []

    def dispatcher_trigger(*_: object) -> bool:
        dispatched.append(1)
        return True

    response = evaluate_conditional_schedule(
        7,
        datetime(2025, 1, 2, tzinfo=timezone.utc),
        evaluation_service_factory=lambda: service,
        dispatcher_trigger=dispatcher_trigger,
    )

    assert response["status"] == PredicateEvaluationStatus.FALSE
    assert response["execution_dispatched"] is False
    assert not dispatched


def test_evaluate_conditional_schedule_bubbles_error_metadata() -> None:
    """Errors should surface error_code/error_message and skip dispatch."""
    error = PredicateEvaluationError(
        error_code="subject_missing",
        error_message="subject not found",
    )
    result = _make_result(PredicateEvaluationStatus.ERROR, message="error", error=error)
    service = _StubEvaluationService(result)

    response = evaluate_conditional_schedule(
        9,
        datetime(2025, 1, 3, tzinfo=timezone.utc),
        evaluation_service_factory=lambda: service,
    )

    assert response["status"] == PredicateEvaluationStatus.ERROR
    assert response["execution_dispatched"] is False
    assert response["error_code"] == "subject_missing"
    assert response["error_message"] == "subject not found"


def test_process_due_retry_executions_enqueues_dispatch(monkeypatch) -> None:
    """Ensure retry scans schedule dispatches for due executions."""
    now = datetime(2025, 1, 4, 12, 0, tzinfo=timezone.utc)
    claim = data_access.RetryExecutionClaim(
        execution_id=11,
        schedule_id=22,
        retry_at=now - timedelta(minutes=1),
    )
    recorded_limits: list[int] = []

    def fake_claim_due_retry_executions(session, when, *, limit):
        recorded_limits.append(limit)
        assert when == now
        return [claim]

    class _FakeSession:
        def commit(self) -> None:
            pass

        def close(self) -> None:
            pass

    class _FakeDispatcher:
        def __init__(self) -> None:
            self.calls: list[tuple[tuple[int, ...], dict[str, object]]] = []

        def apply_async(
            self, args: tuple[int, ...] | None = None, kwargs: dict[str, object] | None = None
        ) -> None:
            self.calls.append((args or (), kwargs or {}))

    dispatcher = _FakeDispatcher()
    monkeypatch.setattr(data_access, "claim_due_retry_executions", fake_claim_due_retry_executions)

    result = process_due_retry_executions(
        session_factory=lambda: _FakeSession(),
        dispatcher_task=dispatcher,
        now=now,
        batch_size=5,
    )

    assert recorded_limits == [5]
    assert dispatcher.calls == [((claim.schedule_id,), {"scheduled_for": claim.retry_at})]
    assert result["scanned"] == 1
    assert result["scheduled"] == 1
    assert result["restored"] == 0


def test_process_due_retry_executions_restores_retry_on_dispatch_failure(monkeypatch) -> None:
    """Dispatch failures should restore the retry_at timestamp for the execution."""
    now = datetime(2025, 1, 4, 12, 0, tzinfo=timezone.utc)
    claim = data_access.RetryExecutionClaim(
        execution_id=99,
        schedule_id=100,
        retry_at=now - timedelta(minutes=2),
    )

    def fake_claim_due_retry_executions(session, when, *, limit):
        return [claim]

    class _FakeSession:
        def commit(self) -> None:
            pass

        def close(self) -> None:
            pass

    class _FailingDispatcher:
        def apply_async(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("retry dispatch failed")

    restored: list[tuple[int, datetime]] = []

    def fake_update_execution(
        session: object,
        execution_id: int,
        updates: data_access.ExecutionUpdateInput,
        actor_context: object,
        *,
        now: datetime,
    ) -> object:
        restored.append((execution_id, updates.next_retry_at))
        return object()

    monkeypatch.setattr(data_access, "claim_due_retry_executions", fake_claim_due_retry_executions)
    monkeypatch.setattr(data_access, "update_execution", fake_update_execution)

    result = process_due_retry_executions(
        session_factory=lambda: _FakeSession(),
        dispatcher_task=_FailingDispatcher(),
        now=now,
        batch_size=1,
    )

    assert result["scanned"] == 1
    assert result["scheduled"] == 0
    assert result["restored"] == 1


def test_persist_schedule_evaluation_updates_next_run(
    monkeypatch,
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure predicate evaluations refresh the conditional schedule next run."""
    now = datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc)
    evaluation_time = now + timedelta(minutes=5)
    actor = data_access.ActorContext(
        actor_type="system",
        actor_id="tester",
        channel="scheduler",
        trace_id="trace-567",
        request_id="req-890",
    )

    with closing(sqlite_session_factory()) as session:
        intent = data_access.create_task_intent(
            session, data_access.TaskIntentInput(summary="conditional check"), actor
        )
        schedule = data_access.create_schedule(
            session,
            data_access.ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="conditional",
                timezone="UTC",
                definition=data_access.ScheduleDefinitionInput(
                    predicate_subject="signal:status",
                    predicate_operator="exists",
                    evaluation_interval_count=10,
                    evaluation_interval_unit="minute",
                ),
            ),
            actor,
            now=now,
        )
        session.commit()
        schedule_id = schedule.id

    monkeypatch.setattr(celery_app, "_session_factory", lambda: sqlite_session_factory())

    result = PredicateEvaluationResult(
        status=PredicateEvaluationStatus.TRUE,
        result_code="ok",
        message=None,
        observed_value=None,
        evaluated_at=evaluation_time,
        error=None,
    )
    celery_app._persist_schedule_evaluation(schedule_id, evaluation_time, result)

    with closing(sqlite_session_factory()) as session:
        refreshed = session.query(Schedule).filter(Schedule.id == schedule_id).first()
    assert refreshed is not None

    def _naive(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=None)

    assert _naive(refreshed.next_run_at) == _naive(evaluation_time + timedelta(minutes=10))


def test_stage2_extract_task_enqueues_stage3(monkeypatch) -> None:
    """Ensure the Stage 2 Celery task enqueues Stage 3 after extraction."""
    from ingestion.retry import StageRetryDecision

    ingestion_id = uuid4()
    recorded: list[UUID] = []

    def fake_run(ingestion_id_arg: UUID) -> Stage2ExtractionResult:
        return Stage2ExtractionResult(
            ingestion_id=ingestion_id_arg,
            extracted_artifacts=1,
            failures=0,
            errors=(),
        )

    def fake_enqueue(ingestion_id_arg: UUID, *, send_task=None) -> None:
        recorded.append(ingestion_id_arg)

    def fake_retry_check(ingestion_id_arg: str, stage: str) -> StageRetryDecision:
        return StageRetryDecision(should_run=True, reason="test")

    monkeypatch.setattr(celery_app, "run_stage2_extraction", fake_run)
    monkeypatch.setattr("ingestion.queue.enqueue_stage3_normalize", fake_enqueue)
    monkeypatch.setattr("scheduler.celery_app.check_should_retry_stage", fake_retry_check)
    payload = {"ingestion_id": str(ingestion_id)}

    response = celery_app.stage2_extract.run(payload)

    assert response["status"] == "completed"
    assert recorded == [ingestion_id]
