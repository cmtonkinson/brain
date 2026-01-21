"""Celery entry point for Brain scheduler callbacks."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from celery import Celery

from attention.router import AttentionRouter
from scheduler.adapters.celery_callback_bridge import (
    CeleryCallbackRequest,
    handle_celery_callback,
)
from scheduler.callback_bridge import CallbackBridge, DispatcherEntrypoint
from scheduler.execution_dispatcher import (
    ExecutionDispatcher,
    ExecutionInvocationResult,
    ExecutionInvoker,
)
from scheduler.failure_notifications import FailureNotificationService
from services.database import get_sync_session
from services.signal import SignalClient

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


def _session_factory():
    """Return a new synchronous SQLAlchemy session for scheduler tasks."""
    return get_sync_session()


class _LoggingExecutionInvoker(ExecutionInvoker):
    """Execution invoker that only logs the invocation result for now."""

    def __init__(self) -> None:
        self._logger = logging.getLogger("brain.scheduler.executions")

    def invoke_execution(self, request) -> ExecutionInvocationResult:
        self._logger.info(
            "Scheduled execution stub invoked: schedule=%s, execution=%s",
            request.execution.schedule_id,
            request.execution.id,
        )
        return ExecutionInvocationResult(
            status="success",
            result_code="noop",
            attention_required=False,
        )


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
    invoker=_LoggingExecutionInvoker(),
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
    )


@celery_app.task(
    bind=True,
    name="scheduler.dispatch",
    acks_late=True,
    autoretry_for=(),
    reject_on_worker_lost=True,
)
def dispatch(self, schedule_id: int, scheduled_for: Any | None = None) -> dict[str, Any]:
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


@celery_app.task(bind=True, name="scheduler.evaluate_predicate")
def evaluate_predicate(self, schedule_id: int) -> dict[str, str]:
    """Placeholder predicate evaluation task; conditional schedules are unsupported."""
    LOGGER.warning(
        "Conditional schedule evaluation is not yet implemented: schedule=%s", schedule_id
    )
    return {"status": "unsupported", "schedule_id": str(schedule_id)}
