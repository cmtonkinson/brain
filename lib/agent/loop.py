"""Headless driver that runs a real PydanticAI ``Agent`` against ``AgentToolModel``.

Headless callers drive identical recovery, repair, and instrumentation
logic by running a ``pydantic_ai.Agent`` whose backing model is the
shared :class:`AgentToolModel`.

Cooperative cancellation is wired in two ways:

* ``cancel_check`` runs immediately before every Language call (via the model
  wrapper below). When the caller's source-of-truth flips to
  ``canceling``, the wrapper raises :class:`CancellationError` which
  propagates out of ``Agent.run_sync`` and is re-raised to the caller.
* ``record_turn`` runs immediately after every Language call, before tool
  dispatch starts on that turn. The same propagation applies for budget
  breaches.

Cancellation can also be triggered mid-tool via the ``on_before_dispatch``
hook the op-tool wrapper invokes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.usage import UsageLimits

from lib.agent.cancellation import (
    CancelDecision,
    CancelReason,
    CancellationError,
    TurnSummary,
)
from lib.agent.tool_model import AgentToolModel
from lib.agent.tools import build_op_tools_from_descriptors
from lib.agent.turn_state import DefaultTurnState
from lib.sdk.calls import OpDescriptor
from lib.sdk.client import BrainClient
from lib.shared.language_model import (
    EnvironmentContextContentPart,
    InferenceEnvironmentItem,
    InferenceSystemBlock,
    ReferenceSnippetContentPart,
    TextContentPart,
)


_DEFAULT_MAX_TURNS: int = 8
"""Default ceiling on Language request count for one headless loop run."""

_TOOL_CALL_RETRIES: int = 1
"""PydanticAI retry count forwarded to the Agent for tool call dispatch."""


@dataclass(frozen=True, slots=True)
class LoopResult:
    """Outcome of one full loop run that reached a terminal text response."""

    final_response: str
    turn_count: int
    exhausted: bool


def run(
    *,
    client: BrainClient,
    system_blocks: tuple[InferenceSystemBlock, ...],
    prompt: str,
    principal: str,
    source: str,
    channel: str,
    session_id: str = "",
    parent_invocation_id: str | None = None,
    tool_allowlist: tuple[str, ...] | None = None,
    max_turns: int = _DEFAULT_MAX_TURNS,
    cancel_check: Callable[[], CancelDecision] | None = None,
    record_turn: Callable[[TurnSummary], CancelDecision] | None = None,
    timeout_seconds: float | None = None,
    context_text: str | None = None,
    context_environment_items: tuple[InferenceEnvironmentItem, ...] = (),
) -> LoopResult:
    """Drive one tool-capable Language conversation to a terminal text response.

    Constructs an ``AgentToolModel`` with a fresh :class:`DefaultTurnState`,
    discovers the op set via ``client.describe_ops``, narrows it through
    the ``tool_allowlist`` (when supplied), and runs a PydanticAI
    ``Agent`` to completion. ``max_turns`` is enforced as a request-count
    ceiling on the underlying ``UsageLimits``; on exhaustion the function
    returns ``exhausted=True`` rather than raising.

    Caller-supplied ``context_text`` and ``context_environment_items``
    flow entirely through structured content parts on the live turn,
    keeping the pipeline IR-canonical from prompt assembly through to
    the LLM adapter boundary.
    """
    descriptors = client.describe_ops()
    if tool_allowlist is not None:
        allowed = frozenset(tool_allowlist)
        descriptors = tuple(item for item in descriptors if item.op_id in allowed)

    turn_state = DefaultTurnState(channel=channel)

    model = _HeadlessAgentModel(
        client=client,
        system_blocks=system_blocks,
        source=source,
        principal=principal,
        session_id=session_id,
        turn_state=turn_state,
        timeout_seconds=timeout_seconds,
        cancel_check=cancel_check,
        record_turn=record_turn,
    )

    on_before_dispatch = _build_on_before_dispatch(cancel_check=cancel_check)
    op_tools = build_op_tools_from_descriptors(
        client=client,
        descriptors=descriptors,
        actor=principal,
        channel=channel,
        parent_invocation_id=parent_invocation_id,
        on_before_dispatch=on_before_dispatch,
    )

    agent = Agent(
        model=model,
        system_prompt="",
        tools=op_tools,
        retries=_TOOL_CALL_RETRIES,
    )

    usage_limits = UsageLimits(request_limit=max(1, max_turns))

    user_content = _build_user_content(
        prompt=prompt,
        context_text=context_text,
        context_environment_items=context_environment_items,
    )

    try:
        result = agent.run_sync(
            user_prompt=user_content,
            usage_limits=usage_limits,
        )
    except CancellationError:
        raise
    except Exception as exc:
        if _is_request_limit_exhaustion(exc):
            return LoopResult(
                final_response=_last_text_from_messages(model.last_messages),
                turn_count=model.turn_count,
                exhausted=True,
            )
        raise

    final_response = ""
    output = getattr(result, "output", None)
    if isinstance(output, str):
        final_response = output
    return LoopResult(
        final_response=final_response,
        turn_count=model.turn_count,
        exhausted=False,
    )


class _HeadlessAgentModel(AgentToolModel):
    """``AgentToolModel`` extension that wires headless cooperative hooks.

    Wraps :meth:`AgentToolModel.request` to fire ``cancel_check`` before
    each Language call and ``record_turn`` after each successful response.
    The underlying request flow is unchanged — this is purely an
    instrumentation seam for the headless driver. Tracking
    ``turn_count`` here lets the driver report it back inside
    :class:`LoopResult` without inspecting PydanticAI's run object.
    """

    def __init__(
        self,
        *,
        cancel_check: Callable[[], CancelDecision] | None,
        record_turn: Callable[[TurnSummary], CancelDecision] | None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._cancel_check = cancel_check
        self._record_turn = record_turn
        self.turn_count = 0
        self.last_messages: list[ModelRequest | ModelResponse] = []

    async def request(  # type: ignore[override]
        self,
        messages: list[ModelRequest | ModelResponse],
        model_settings: object,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        self.last_messages = list(messages)
        if self._cancel_check is not None:
            decision = self._cancel_check()
            if decision.should_stop:
                raise CancellationError(decision.reason or CancelReason.manual)
        response = await super().request(
            messages, model_settings, model_request_parameters
        )
        self.turn_count += 1
        if self._record_turn is not None:
            decision = self._record_turn(TurnSummary(turn_index=self.turn_count - 1))
            if decision.should_stop:
                raise CancellationError(decision.reason or CancelReason.budget_tokens)
        return response


def _build_on_before_dispatch(
    *,
    cancel_check: Callable[[], CancelDecision] | None,
) -> Callable[[OpDescriptor], None] | None:
    """Build the dispatch-time cancellation hook for op-tool wrappers."""
    if cancel_check is None:
        return None

    def _check(_descriptor: OpDescriptor) -> None:
        decision = cancel_check()
        if decision.should_stop:
            raise CancellationError(decision.reason or CancelReason.manual)

    return _check


def _build_user_content(
    *,
    prompt: str,
    context_text: str | None,
    context_environment_items: tuple[InferenceEnvironmentItem, ...],
) -> list[Any]:
    """Compose the structured ``UserContent`` list for the live turn.

    Caller-supplied context flows entirely through canonical content parts
    so the IR builder can route them into the right structured slots
    (memory reference snippets, environment context). Plain text prompts
    travel as ``TextContentPart`` rather than as raw strings to keep the
    pipeline IR-only end-to-end; only the LLM Adapter ever flattens.
    """
    content: list[Any] = []
    if context_text is not None and context_text.strip() != "":
        content.append(ReferenceSnippetContentPart(text=context_text))
    if context_environment_items:
        content.append(
            EnvironmentContextContentPart(items=tuple(context_environment_items))
        )
    if prompt != "":
        content.append(TextContentPart(text=prompt))
    return content


def _is_request_limit_exhaustion(exc: BaseException) -> bool:
    """Detect PydanticAI's request-limit exhaustion in a version-tolerant way.

    PydanticAI raises ``UsageLimitExceeded`` (and aliases) when a configured
    ``request_limit`` is hit. Match by class name to avoid a hard import
    against an unstable submodule path.
    """
    name = type(exc).__name__
    if "UsageLimit" in name and "Exceed" in name:
        return True
    return False


def _last_text_from_messages(messages: list[ModelRequest | ModelResponse]) -> str:
    """Extract the last assistant text response from a PydanticAI message list."""
    for message in reversed(messages):
        if not isinstance(message, ModelResponse):
            continue
        for part in message.parts:
            text = getattr(part, "content", None)
            if isinstance(text, str) and text.strip() != "":
                return text
    return ""


__all__ = ["LoopResult", "run"]
