"""Native agent invoker used by the scheduler dispatcher."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable

from agent import Agent, AgentDeps, _ensure_llm_env, _extract_agent_response, create_agent
from config import settings
from prompts import render_prompt
from scheduler.execution_dispatcher import (
    ExecutionInvocationError,
    ExecutionInvocationRequest,
    ExecutionInvocationResult,
    ExecutionInvoker,
    ExecutionInvocationScheduleDefinition,
)
from services.code_mode import CodeModeManager, create_code_mode_manager
from tools.memory import ConversationMemory
from tools.obsidian import ObsidianClient

LOGGER = logging.getLogger(__name__)


def _format_datetime(value: datetime | None) -> str:
    """Return an ISO-formatted timestamp or 'None' when missing."""
    if value is None:
        return "None"
    return value.astimezone(timezone.utc).isoformat()


def _definition_to_string(definition: ExecutionInvocationScheduleDefinition) -> str:
    """Serialize the typed schedule definition into a compact text representation."""
    parts: list[str] = []
    if definition.run_at is not None:
        parts.append(f"run_at={_format_datetime(definition.run_at)}")
    if definition.interval_count is not None and definition.interval_unit:
        parts.append(f"interval={definition.interval_count} {definition.interval_unit}")
    if definition.anchor_at is not None:
        parts.append(f"anchor_at={_format_datetime(definition.anchor_at)}")
    if definition.rrule:
        parts.append(f"rrule={definition.rrule}")
    if definition.calendar_anchor_at is not None:
        parts.append(f"calendar_anchor_at={_format_datetime(definition.calendar_anchor_at)}")
    if definition.predicate_subject:
        predicate = definition.predicate_operator or "unknown"
        parts.append(
            f"predicate={definition.predicate_subject} {predicate} {definition.predicate_value or 'None'}"
        )
    if definition.evaluation_interval_count and definition.evaluation_interval_unit:
        parts.append(
            f"evaluation_interval={definition.evaluation_interval_count} {definition.evaluation_interval_unit}"
        )
    return "; ".join(parts) if parts else "None"


def _run_coroutine_sync(coro: Callable[[], object]) -> object:
    """Run an async coroutine in a fresh asyncio runner and return the result."""
    runner = asyncio.Runner()
    try:
        return runner.run(coro())
    finally:
        runner.close()


class AgentExecutionInvoker(ExecutionInvoker):
    """Execution invoker that runs the Brain agent code within the scheduler stack."""

    PROMPT_NAME = "system/scheduled-execution"

    def __init__(
        self,
        *,
        agent: Agent[AgentDeps, str] | None = None,
        obsidian: ObsidianClient | None = None,
        memory: ConversationMemory | None = None,
        code_mode: CodeModeManager | None = None,
    ) -> None:
        """Initialize the invoker with cached dependencies."""
        _ensure_llm_env()
        self._agent = agent or create_agent()
        self._obsidian = obsidian or ObsidianClient()
        self._memory = memory or ConversationMemory(self._obsidian)
        self._code_mode = code_mode or self._build_code_mode_manager()

    def _build_code_mode_manager(self) -> CodeModeManager:
        """Create the Code-Mode manager used by the agent invocation."""
        return _run_coroutine_sync(
            lambda: create_code_mode_manager(
                settings.utcp.config_path,
                settings.utcp.code_mode_timeout,
            )
        )

    def _build_prompt(self, request: ExecutionInvocationRequest) -> str:
        """Render the scheduled-execution prompt with metadata placeholders."""
        return render_prompt(
            self.PROMPT_NAME,
            {
                "task_summary": request.task_intent.summary,
                "task_details": request.task_intent.details or "None",
                "origin_reference": request.task_intent.origin_reference or "None",
                "schedule_type": request.schedule.schedule_type,
                "schedule_timezone": request.schedule.timezone or "UTC",
                "schedule_definition": _definition_to_string(request.schedule.definition),
                "scheduled_for": _format_datetime(request.execution.scheduled_for),
                "next_run_at": _format_datetime(request.schedule.next_run_at),
                "last_run_at": _format_datetime(request.schedule.last_run_at),
                "last_run_status": request.schedule.last_run_status or "None",
                "attempt_number": request.execution.attempt_number,
                "max_attempts": request.execution.max_attempts,
                "backoff_strategy": request.execution.backoff_strategy or "none",
                "retry_after": _format_datetime(request.execution.retry_after),
                "trigger_source": request.execution_metadata.trigger_source,
                "callback_id": request.execution_metadata.callback_id or "None",
                "trace_id": request.execution.trace_id,
            },
        )

    def _invoke_agent(self, prompt: str) -> str:
        """Run the agent with the scheduled prompt and return its normalized response."""

        def _coro():
            deps = AgentDeps(
                user=settings.user.name,
                obsidian=self._obsidian,
                memory=self._memory,
                code_mode=self._code_mode,
                signal_sender=None,
                channel="scheduled",
            )
            return self._agent.run(prompt, deps=deps)

        result = _run_coroutine_sync(_coro)
        return _extract_agent_response(result)

    def invoke_execution(self, request: ExecutionInvocationRequest) -> ExecutionInvocationResult:
        """Invoke the agent for a scheduled execution."""
        prompt = self._build_prompt(request)
        try:
            response = self._invoke_agent(prompt)
            trimmed = response.strip() if response else ""
            return ExecutionInvocationResult(
                status="success",
                result_code="ok",
                attention_required=bool(trimmed),
                message=trimmed or None,
            )
        except Exception as exc:
            LOGGER.exception("Scheduled agent invocation failed")
            return ExecutionInvocationResult(
                status="failure",
                result_code="agent_error",
                attention_required=True,
                message=str(exc),
                error=ExecutionInvocationError(
                    error_code="agent_error",
                    error_message=str(exc),
                ),
            )
