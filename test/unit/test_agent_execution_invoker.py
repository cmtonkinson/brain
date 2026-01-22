"""Unit tests for the native scheduler agent invoker."""

from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timezone

from scheduler.agent_invoker import AgentExecutionInvoker
from scheduler.execution_dispatcher import (
    ExecutionInvocationRequest,
    ExecutionInvocationExecution,
    ExecutionInvocationMetadata,
    ExecutionInvocationSchedule,
    ExecutionInvocationScheduleDefinition,
    ExecutionInvocationTaskIntent,
    ExecutionInvocationActorContext,
    ExecutionInvocationResult,
)


class _FakeAgent:
    def __init__(self, response: str | None = "ok", *, raise_exc: bool = False):
        self.response = response
        self.raise_exc = raise_exc

    async def run(self, prompt: str, deps) -> SimpleNamespace:
        del prompt
        del deps
        if self.raise_exc:
            raise RuntimeError("agent failed")
        return SimpleNamespace(output=self.response)


class _FakeMemory:
    async def log_message(self, *args, **kwargs):
        del args, kwargs

    async def get_recent_context(self, *args, **kwargs):
        del args, kwargs
        return None

    def should_write_summary(self, *args, **kwargs):
        del args, kwargs
        return False

    async def log_summary(self, *args, **kwargs) -> str:
        del args, kwargs
        return "summary"

    async def log_summary_marker(self, *args, **kwargs):
        del args, kwargs


class _FakeCodeMode:
    client = None
    config_path = None
    timeout = 0


class _DummyObsidian:
    pass


def _build_request() -> ExecutionInvocationRequest:
    now = datetime(2025, 2, 7, 10, 0, tzinfo=timezone.utc)
    execution = ExecutionInvocationExecution(
        id=1,
        schedule_id=1,
        task_intent_id=1,
        scheduled_for=now,
        attempt_number=1,
        max_attempts=3,
        backoff_strategy="exponential",
        retry_after=now,
        trace_id="trace-1",
    )
    task_intent = ExecutionInvocationTaskIntent(
        summary="summary",
        details="details",
        origin_reference="origin",
    )
    definition = ExecutionInvocationScheduleDefinition(
        run_at=now,
        interval_count=1,
        interval_unit=None,
        anchor_at=None,
        rrule=None,
        calendar_anchor_at=None,
        predicate_subject=None,
        predicate_operator=None,
        predicate_value=None,
        evaluation_interval_count=None,
        evaluation_interval_unit=None,
    )
    schedule = ExecutionInvocationSchedule(
        schedule_type="one_time",
        timezone="UTC",
        definition=definition,
        next_run_at=now,
        last_run_at=None,
        last_run_status=None,
    )
    actor_context = ExecutionInvocationActorContext(
        actor_type="scheduled",
        actor_id=None,
        channel="scheduled",
        privilege_level="constrained",
        autonomy_level="limited",
        trace_id="trace-1",
        request_id=None,
    )
    metadata = ExecutionInvocationMetadata(
        actual_started_at=now,
        trigger_source="scheduler_callback",
        callback_id="callback-1",
    )
    return ExecutionInvocationRequest(
        execution=execution,
        task_intent=task_intent,
        schedule=schedule,
        actor_context=actor_context,
        execution_metadata=metadata,
    )


def test_agent_execution_invoker_returns_success_message() -> None:
    invoker = AgentExecutionInvoker(
        agent=_FakeAgent("done"),
        obsidian=_DummyObsidian(),
        memory=_FakeMemory(),
        code_mode=_FakeCodeMode(),
    )
    result = invoker.invoke_execution(_build_request())
    assert isinstance(result, ExecutionInvocationResult)
    assert result.status == "success"
    assert result.message == "done"
    assert result.attention_required is True


def test_agent_execution_invoker_captures_errors() -> None:
    invoker = AgentExecutionInvoker(
        agent=_FakeAgent(None, raise_exc=True),
        obsidian=_DummyObsidian(),
        memory=_FakeMemory(),
        code_mode=_FakeCodeMode(),
    )
    result = invoker.invoke_execution(_build_request())
    assert result.status == "failure"
    assert result.error is not None
    assert result.error.error_code == "agent_error"
