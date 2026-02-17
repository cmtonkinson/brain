"""Native agent invoker used by the scheduler dispatcher."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable

from agent import Agent, AgentDeps, _ensure_llm_env, _extract_agent_response, create_agent
from commitments.scheduled_tasks import (
    CommitmentScheduledTaskHandler,
    CommitmentScheduledTaskResult,
)
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
from services.object_store import ObjectStore
from tools.memory import ConversationMemory
from tools.obsidian import ObsidianClient
from attention.router import AttentionRouter
from llm import LLMClient
from sqlalchemy.orm import Session

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
    """Run an async coroutine synchronously.

    If called from outside an event loop, creates a new runner.
    If called from within an event loop, raises an error since we can't block.
    """
    try:
        # Check if we're already in an event loop
        asyncio.get_running_loop()
        # If we get here, there IS a running loop - we can't use Runner()
        raise RuntimeError(
            "Cannot synchronously initialize CodeModeManager from within an event loop. "
            "AgentExecutionInvoker must be created outside async context, "
            "or pass code_mode explicitly to avoid lazy initialization."
        )
    except RuntimeError as e:
        # Check if the error is about no running loop (expected case)
        error_msg = str(e).lower()
        if "no running event loop" in error_msg or "no current event loop" in error_msg:
            # No running loop - safe to create a new runner
            runner = asyncio.Runner()
            try:
                return runner.run(coro())
            finally:
                runner.close()
        else:
            # It's our custom error or another RuntimeError - re-raise
            raise


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
        session_factory: Callable[[], Session] | None = None,
        router: AttentionRouter | None = None,
        commitment_handler: CommitmentScheduledTaskHandler | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        """Initialize the invoker with cached dependencies."""
        _ensure_llm_env()
        self._agent = agent or create_agent()
        self._obsidian = obsidian or ObsidianClient()
        self._memory = memory or ConversationMemory(self._obsidian)
        self._code_mode = code_mode or self._build_code_mode_manager()
        self._object_store = ObjectStore(settings.objects.root_dir)
        if commitment_handler is not None:
            self._commitment_handler = commitment_handler
        elif session_factory is not None and router is not None:
            self._commitment_handler = CommitmentScheduledTaskHandler(
                session_factory,
                router,
                owner=settings.user.name,
                llm_client=llm_client,
            )
        else:
            self._commitment_handler = None

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
                object_store=self._object_store,
                signal_sender=None,
                channel="scheduled",
            )
            return self._agent.run(prompt, deps=deps)

        result = _run_coroutine_sync(_coro)
        return _extract_agent_response(result)

    def invoke_execution(self, request: ExecutionInvocationRequest) -> ExecutionInvocationResult:
        """Invoke the agent for a scheduled execution."""
        commitment_result = self._handle_commitment_task(request)
        if commitment_result is not None:
            return commitment_result
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

    def _handle_commitment_task(
        self,
        request: ExecutionInvocationRequest,
    ) -> ExecutionInvocationResult | None:
        """Handle commitment-origin scheduled tasks without invoking the LLM agent."""
        if self._commitment_handler is None:
            return None
        try:
            outcome = self._commitment_handler.handle(
                origin_reference=request.task_intent.origin_reference,
                schedule_id=request.execution.schedule_id,
                trace_id=request.execution.trace_id,
                scheduled_for=request.execution.scheduled_for,
            )
        except Exception as exc:
            LOGGER.exception("Commitment scheduled task handling failed")
            return ExecutionInvocationResult(
                status="failure",
                result_code="commitment_task_error",
                attention_required=True,
                message=str(exc),
                error=ExecutionInvocationError(
                    error_code="commitment_task_error",
                    error_message=str(exc),
                ),
            )
        if outcome is None:
            return None
        return _result_from_commitment_outcome(outcome)


def _result_from_commitment_outcome(
    outcome: CommitmentScheduledTaskResult,
) -> ExecutionInvocationResult:
    """Translate a commitment task outcome into a scheduler invocation result."""
    if outcome.status == "failed":
        error_code = outcome.error_code or "commitment_task_failed"
        return ExecutionInvocationResult(
            status="failure",
            result_code=error_code,
            attention_required=True,
            message=outcome.message,
            error=ExecutionInvocationError(
                error_code=error_code,
                error_message=outcome.message or error_code,
            ),
        )
    return ExecutionInvocationResult(
        status="success",
        result_code="commitment_task",
        attention_required=outcome.attention_required,
        message=outcome.message,
    )
