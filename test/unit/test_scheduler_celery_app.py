"""Unit tests for the scheduler Celery evaluate_predicate helper."""

from datetime import datetime, timezone

from scheduler.celery_app import evaluate_conditional_schedule
from scheduler.predicate_evaluation import (
    PredicateEvaluationError,
    PredicateEvaluationResult,
    PredicateEvaluationStatus,
)


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
