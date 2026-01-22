"""Celery entry point for Brain scheduler callbacks."""

from __future__ import annotations

from contextlib import closing
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from celery import Celery

from attention.router import AttentionRouter
from scheduler.adapters.celery_callback_bridge import (
    CeleryCallbackRequest,
    handle_celery_callback,
)
from scheduler.agent_invoker import AgentExecutionInvoker
from scheduler import data_access
from scheduler.callback_bridge import CallbackBridge, DispatcherEntrypoint
from scheduler.execution_dispatcher import ExecutionDispatcher
from scheduler.failure_notifications import FailureNotificationService
from scheduler.predicate_evaluation import (
    PredicateEvaluationErrorCode,
    PredicateEvaluationResult,
    PredicateEvaluationService,
    PredicateEvaluationServiceError,
    PredicateEvaluationStatus,
    SubjectResolver,
)
from scheduler.predicate_evaluation_audit import PredicateEvaluationAuditRecorder
from services.database import get_sync_session
from services.signal import SignalClient
from models import Schedule

LOGGER = logging.getLogger(__name__)


def _env(var: str, default: str) -> str:
    return os.environ.get(var, default)


celery_app = Celery("brain.scheduler")
celery_app.conf.broker_url = _env("CELERY_BROKER_URL", "redis://redis:6379/1")
celery_app.conf.result_backend = _env("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
celery_app.conf.task_default_queue = _env("CELERY_QUEUE_NAME", "scheduler")
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.enable_utc = True
celery_app.conf.timezone = "UTC"

_RETRY_SCAN_INTERVAL_SECONDS = float(_env("SCHEDULER_RETRY_SCAN_INTERVAL_SECONDS", "60"))
_RETRY_SCAN_BATCH_SIZE = int(_env("SCHEDULER_RETRY_SCAN_BATCH_SIZE", "100"))
beat_schedule = celery_app.conf.get("beat_schedule")
if beat_schedule is None:
    beat_schedule = {}
beat_schedule["scheduler.enqueue_retry_callbacks"] = {
    "task": "scheduler.enqueue_retry_callbacks",
    "schedule": _RETRY_SCAN_INTERVAL_SECONDS,
}
celery_app.conf.beat_schedule = beat_schedule


def _session_factory():
    """Return a new synchronous SQLAlchemy session for scheduler tasks."""
    return get_sync_session()


class _DispatcherEntrypointAdapter(DispatcherEntrypoint):
    """Adapter that exposes the ExecutionDispatcher via the dispatcher protocol."""

    def __init__(self, dispatcher: ExecutionDispatcher) -> None:
        self._dispatcher = dispatcher

    def dispatch(self, payload) -> None:
        self._dispatcher.dispatch(payload)


_ROUTER = AttentionRouter(
    signal_client=SignalClient(),
    session_factory=_session_factory,
)
_FAILURE_NOTIFIER = FailureNotificationService(
    session_factory=_session_factory,
    router=_ROUTER,
)
_DISPATCHER = ExecutionDispatcher(
    session_factory=_session_factory,
    invoker=AgentExecutionInvoker(),
    failure_notifier=_FAILURE_NOTIFIER,
)
_BRIDGE = CallbackBridge(
    session_factory=_session_factory,
    dispatcher=_DispatcherEntrypointAdapter(_DISPATCHER),
)


def _coerce_datetime(value: Any) -> datetime | None:
    """Coerce a JSON-serializable value into an aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        return datetime.fromisoformat(text)
    raise ValueError(f"Unsupported datetime format: {value!r}")


def _build_trace_id(schedule_id: int) -> str:
    """Create a stable trace id for scheduled callbacks."""
    return f"schedule:{schedule_id}:{uuid4().hex}"


def _build_callback_request(
    *,
    schedule_id: int,
    scheduled_for: datetime | None,
    provider_task_id: str | None,
    trigger_source: str = "scheduler_callback",
) -> CeleryCallbackRequest:
    """Build the Celery callback payload that flows into the dispatcher."""
    now = datetime.now(timezone.utc)
    return CeleryCallbackRequest(
        schedule_id=schedule_id,
        scheduled_for=scheduled_for or now,
        trace_id=_build_trace_id(schedule_id),
        emitted_at=now,
        provider_attempt=1,
        provider_task_id=provider_task_id,
        trigger_source=trigger_source,
    )


_EVALUATION_TASK_NAME = "scheduler.evaluate_predicate"


class _UnsupportedSubjectResolver(SubjectResolver):
    """Fallback resolver used when no real subject resolver is configured."""

    def resolve(
        self,
        subject: str,
        actor_context: object,
    ) -> str | int | float | bool | None:
        """Raise a structured error indicating the subject is not implemented."""
        raise PredicateEvaluationServiceError(
            code=PredicateEvaluationErrorCode.SUBJECT_NOT_FOUND.value,
            message=f"Subject '{subject}' resolution is not implemented.",
        )


def _default_subject_resolver() -> SubjectResolver:
    """Return the default placeholder subject resolver."""
    return _UnsupportedSubjectResolver()


_subject_resolver_factory: Callable[[], SubjectResolver] = _default_subject_resolver


def _default_evaluation_service_factory() -> PredicateEvaluationService:
    """Build the production predicate evaluation service."""
    return PredicateEvaluationService(
        session_factory=_session_factory,
        subject_resolver=_subject_resolver_factory(),
        audit_recorder=PredicateEvaluationAuditRecorder(_session_factory),
    )


_evaluation_service_factory: Callable[[], PredicateEvaluationService] = (
    _default_evaluation_service_factory
)


def _persist_schedule_evaluation(
    schedule_id: int,
    evaluation_time: datetime,
    result: PredicateEvaluationResult,
) -> None:
    """Store the latest predicate evaluation metadata on the schedule."""
    try:
        with closing(_session_factory()) as session:
            schedule = session.query(Schedule).filter(Schedule.id == schedule_id).first()
            if schedule is None:
                LOGGER.warning(
                    "Skipping predicate evaluation persistence for unknown schedule %s",
                    schedule_id,
                )
                return
            schedule.last_evaluated_at = evaluation_time
            schedule.last_evaluation_status = str(result.status)
            schedule.last_evaluation_error_code = result.error.error_code if result.error else None
            session.commit()
    except Exception:
        LOGGER.exception(
            "Failed to persist predicate evaluation metadata: schedule=%s", schedule_id
        )


def _dispatch_conditional_execution(schedule_id: int, scheduled_for: datetime) -> bool:
    """Trigger the execution flow for a conditional schedule after a positive predicate."""
    request = _build_callback_request(
        schedule_id=schedule_id,
        scheduled_for=scheduled_for,
        provider_task_id=None,
    )
    try:
        result = handle_celery_callback(request, _BRIDGE)
        LOGGER.info(
            "Conditional execution dispatch result: schedule=%s status=%s",
            schedule_id,
            result.status,
        )
        return result.status in {"accepted", "duplicate"}
    except Exception:
        LOGGER.exception("Failed to dispatch execution for conditional schedule: %s", schedule_id)
        return False


def process_due_retry_executions(
    *,
    session_factory: Callable[[], Session],
    dispatcher_task: Any,
    now: datetime,
    batch_size: int,
) -> dict[str, int]:
    """Scan for retry_scheduled executions that are due and enqueue callbacks."""
    now = now.astimezone(timezone.utc)
    with closing(session_factory()) as session:
        claims = data_access.claim_due_retry_executions(session, now, limit=batch_size)
        session.commit()

    scheduled = 0
    restored = 0
    for claim in claims:
        try:
            dispatcher_task.apply_async(
                args=(claim.schedule_id,),
                kwargs={"scheduled_for": claim.retry_at},
            )
            scheduled += 1
        except Exception:
            _restore_retry_claim(claim, session_factory)
            restored += 1

    LOGGER.info(
        "Retry scan completed: scanned=%s scheduled=%s restored=%s",
        len(claims),
        scheduled,
        restored,
    )
    return {"scanned": len(claims), "scheduled": scheduled, "restored": restored}


def _restore_retry_claim(
    claim: data_access.RetryExecutionClaim,
    session_factory: Callable[[], Session],
) -> None:
    """Restore the next_retry_at value when scheduling a retry callback fails."""
    try:
        with closing(session_factory()) as session:
            actor_context = data_access.ExecutionActorContext(
                actor_type="system",
                actor_id=None,
                channel="scheduler",
                trace_id=f"retry_restore:{claim.execution_id}:{uuid4().hex}",
                actor_context=f"retry_restore:{claim.execution_id}",
            )
            data_access.update_execution(
                session,
                claim.execution_id,
                data_access.ExecutionUpdateInput(next_retry_at=claim.retry_at),
                actor_context,
                now=datetime.now(timezone.utc),
            )
            session.commit()
    except Exception:
        LOGGER.exception(
            "Failed to restore next_retry_at for execution=%s",
            claim.execution_id,
        )


def evaluate_conditional_schedule(
    schedule_id: int,
    scheduled_for: Any | None,
    *,
    evaluation_service_factory: Callable[[], PredicateEvaluationService] | None = None,
    metadata_persistor: Callable[[int, datetime, PredicateEvaluationResult], None] | None = (None),
    dispatcher_trigger: Callable[[int, datetime], bool] | None = None,
    provider_name: str | None = None,
    provider_attempt: int | None = None,
    trace_id: str | None = None,
    evaluation_id: str | None = None,
) -> dict[str, object]:
    """Core logic for running predicate evaluation and dispatching executions."""
    evaluation_time = _coerce_datetime(scheduled_for) or datetime.now(timezone.utc)
    evaluation_id = evaluation_id or f"predicate:{schedule_id}:{uuid4().hex}"
    provider_name = provider_name or _EVALUATION_TASK_NAME
    provider_attempt = provider_attempt or 1
    trace_id = trace_id or f"{provider_name}:{schedule_id}:{uuid4().hex}"
    service_factory = evaluation_service_factory or _evaluation_service_factory
    service = service_factory()
    result = service.evaluate_schedule(
        schedule_id=schedule_id,
        evaluation_id=evaluation_id,
        evaluation_time=evaluation_time,
        provider_name=provider_name,
        provider_attempt=provider_attempt,
        trace_id=trace_id,
    )
    persistor = metadata_persistor or _persist_schedule_evaluation
    try:
        persistor(schedule_id, evaluation_time, result)
    except Exception:
        LOGGER.exception("Error persisting predicate evaluation metadata: schedule=%s", schedule_id)
    executed = False
    if result.status == PredicateEvaluationStatus.TRUE:
        dispatcher = dispatcher_trigger or _dispatch_conditional_execution
        executed = dispatcher(schedule_id, evaluation_time)
    LOGGER.info(
        "Predicate evaluation completed: schedule=%s status=%s dispatched=%s",
        schedule_id,
        result.status,
        executed,
    )
    return {
        "status": result.status,
        "evaluation_id": evaluation_id,
        "schedule_id": schedule_id,
        "provider_attempt": provider_attempt,
        "result_code": result.result_code,
        "message": result.message,
        "error_code": result.error.error_code if result.error else None,
        "error_message": result.error.error_message if result.error else None,
        "execution_dispatched": executed,
    }


@celery_app.task(
    bind=True,
    name="scheduler.dispatch",
    acks_late=True,
    autoretry_for=(),
    reject_on_worker_lost=True,
)
def dispatch(
    self,
    schedule_id: int,
    scheduled_for: Any | None = None,
    trigger_source: str | None = None,
) -> dict[str, Any]:
    """Handle provider callbacks by routing them through the scheduler dispatcher."""
    try:
        scheduled = _coerce_datetime(scheduled_for)
    except ValueError as exc:
        LOGGER.error("Invalid scheduled_for value for schedule %s: %s", schedule_id, exc)
        raise

    request = _build_callback_request(
        schedule_id=schedule_id,
        scheduled_for=scheduled,
        provider_task_id=getattr(self.request, "id", None),
        trigger_source=trigger_source or "scheduler_callback",
    )

    result = handle_celery_callback(request, _BRIDGE)
    LOGGER.info(
        "Celery dispatch completed: schedule=%s status=%s duplicate=%s",
        schedule_id,
        result.status,
        result.duplicate_execution_id,
    )
    return {
        "status": result.status,
        "duplicate_execution_id": result.duplicate_execution_id,
    }


@celery_app.task(name="scheduler.enqueue_retry_callbacks")
def enqueue_retry_callbacks() -> dict[str, int]:
    """Celery beat job that re-enqueues retry callbacks."""
    return process_due_retry_executions(
        session_factory=_session_factory,
        dispatcher_task=dispatch,
        now=datetime.now(timezone.utc),
        batch_size=_RETRY_SCAN_BATCH_SIZE,
    )


@celery_app.task(bind=True, name="scheduler.evaluate_predicate")
def evaluate_predicate(
    self,
    schedule_id: int,
    scheduled_for: Any | None = None,
) -> dict[str, object]:
    """Evaluate the predicate for a conditional schedule and trigger execution if needed."""
    provider_attempt = getattr(self.request, "retries", 0) + 1
    trace_id = getattr(self.request, "id", None)
    return evaluate_conditional_schedule(
        schedule_id,
        scheduled_for,
        provider_name=self.name,
        provider_attempt=provider_attempt,
        trace_id=trace_id,
    )
