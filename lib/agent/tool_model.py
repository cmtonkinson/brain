"""``AgentToolModel`` — the PydanticAI ``Model`` adapter shared by every
agent runtime in the system.

Both ``actors/assistant`` and ``actors/subagent`` consume this class so every
Language turn flows through identical recovery, repair, and instrumentation
logic.

Two pieces of operator-specific behaviour are parameterized via the
constructor:

* ``turn_state`` needs to satisfy only the
  :class:`lib.agent.turn_state.TurnState` Protocol; the operator-facing
  Agent passes its rich turn-state dataclass while the Subagent passes
  :class:`DefaultTurnState`.
* ``operator_recovery_notifier`` is an optional async callback invoked
  when the model detects a recoverable Language failure that warrants
  surfacing an in-progress notice to the operator. The Agent wires its
  recovery notifier here; the Subagent passes ``None`` and the notice
  path is skipped entirely.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable, Protocol

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.profiles import ModelProfile

from lib.agent.inference import normalize_finish_reason, partition_returned_tool_calls
from lib.agent.inference_request import (
    allow_parallel_tool_calls,
    build_inference_request,
    to_model_tool_call,
)
from lib.agent.recovery import (
    INVALID_TOOL_CALL_REPAIR_ATTEMPTS,
    INVALID_TOOL_CALL_RETRY_INSTRUCTION,
    LMS_PROVIDER_RETRY_DELAYS_SECONDS,
    LMS_RECOVERY_NOTICE_DELAY_THRESHOLD_SECONDS,
    language_recovery_profile_sequence,
    should_notify_operator_of_language_recovery,
    should_retry_language_failure,
)
from lib.shared.observability import set_current_span_attributes
from lib.agent.turn_state import DefaultTurnState, TurnState
from lib.sdk.calls import LmsChatToolCall, LmsToolChatResult
from lib.sdk.errors import BrainInternalError, BrainSdkError, SdkErrorDetail
from lib.sdk.meta import MetaOverrides
from lib.shared.language_model import InferenceSystemBlock
from lib.shared.logging import get_logger


class _LmsClient(Protocol):
    """Minimal SDK surface required by the model for one tool-capable Language call."""

    def language_chat_with_tools(
        self, *args: Any, **kwargs: Any
    ) -> LmsToolChatResult: ...


_LOGGER = get_logger(__name__)

_EMPTY_RESPONSE_FALLBACK = "I do not have a response yet."


OperatorRecoveryNotifier = Callable[..., Awaitable[None]]
"""Callback signature for surfacing an Language-recovery notice to the operator.

Caller supplies an async function with at minimum the keyword arguments
``client``, ``turn_state``, ``session_id``, ``message``, and
``reasoning_level``. ``AgentToolModel`` invokes it via ``await
operator_recovery_notifier(...)`` only when ``should_notify_operator``
returns True for a recoverable failure.
"""


OperatorIntermediateTextNotifier = Callable[..., Awaitable[None]]
"""Callback signature for surfacing intermediate model text to the operator.

Caller supplies an async function with at minimum the keyword arguments
``client``, ``turn_state``, ``session_id``, ``text``, and
``reasoning_level``. ``AgentToolModel`` invokes it via ``await
operator_intermediate_text_notifier(...)`` whenever a successful model
response carries both non-empty text *and* one or more valid tool calls,
so the operator can see the model's commentary as the turn unfolds. The
callback owns channel selection and any presentation formatting; the
model passes the raw model-emitted text.
"""


class AgentToolModel(Model):
    """PydanticAI model backed by the SDK tool-capable Language endpoint.

    Owns a turn-scoped recovery state machine: provider retries, profile
    fallback, and invalid-tool-call repair. The class itself is
    operator-neutral; agent-specific concerns (operator notification,
    pending-invocation accounting, dynamic tool exposure) belong to the
    caller and reach this class only through the ``turn_state`` Protocol
    and the optional ``operator_recovery_notifier`` callback.
    """

    def __init__(
        self,
        *,
        client: _LmsClient,
        system_blocks: tuple[InferenceSystemBlock, ...],
        source: str,
        principal: str,
        session_id: str,
        turn_state: TurnState | None = None,
        profile_name: str = "standard",
        timeout_seconds: float | None = None,
        tool_approvals: dict[str, str | None] | None = None,
        extra_input_properties: dict[str, object] | None = None,
        discovery_tool_names: frozenset[str] = frozenset(),
        operator_recovery_notifier: OperatorRecoveryNotifier | None = None,
        recovery_notice_message: str = "",
        operator_intermediate_text_notifier: OperatorIntermediateTextNotifier
        | None = None,
    ) -> None:
        super().__init__(profile=ModelProfile(supports_tools=True))
        self._client = client
        self._turn_state = DefaultTurnState() if turn_state is None else turn_state
        self._profile_name = profile_name
        self._timeout_seconds = timeout_seconds
        self._session_id = session_id
        self._source = source
        self._principal = principal
        self._system_blocks = system_blocks
        self._tool_approvals = {} if tool_approvals is None else dict(tool_approvals)
        self._extra_input_properties = extra_input_properties
        self._discovery_tool_names = discovery_tool_names
        self._operator_recovery_notifier = operator_recovery_notifier
        self._recovery_notice_message = recovery_notice_message
        self._operator_intermediate_text_notifier = operator_intermediate_text_notifier
        self.last_result: LmsToolChatResult | None = None
        self._last_used_profile_name = profile_name

    async def request(
        self,
        messages: list[ModelRequest | ModelResponse],
        model_settings: object,  # noqa: ARG002 — required by Model interface, unused here
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Request one tool-capable model response from the SDK-backed Language."""
        _, prepared_params = self.prepare_request(None, model_request_parameters)
        request_meta = self._turn_state.next_model_meta()
        original_profile_name = self.profile_name
        cumulative_retry_delay_seconds = 0.0
        advertised_tool_names = [item.name for item in prepared_params.function_tools]
        last_exc: BrainSdkError | None = None

        def _recovery_notice_due(*, profile_index: int, next_delay: float) -> bool:
            if self._turn_state.language_recovery_notice_sent:
                return False
            if profile_index > 0:
                return True
            return (
                cumulative_retry_delay_seconds + next_delay
                >= LMS_RECOVERY_NOTICE_DELAY_THRESHOLD_SECONDS
            )

        try:
            for profile_index, profile_name in enumerate(
                language_recovery_profile_sequence(original_profile_name)
            ):
                self.set_profile_name(profile_name)
                for provider_attempt in range(
                    len(LMS_PROVIDER_RETRY_DELAYS_SECONDS) + 1
                ):
                    system_blocks = self._system_blocks
                    result: LmsToolChatResult | None = None
                    valid_tool_calls: tuple[LmsChatToolCall, ...] = ()
                    invalid_tool_names: tuple[str, ...] = ()
                    try:
                        for repair_attempt in range(INVALID_TOOL_CALL_REPAIR_ATTEMPTS):
                            inference_request = build_inference_request(
                                session_id=self._session_id,
                                conversation_episode_id=self._turn_state.conversation_episode_id,
                                source=self._source,
                                principal=self._principal,
                                meta=request_meta,
                                system_blocks=system_blocks,
                                messages=messages,
                                tool_defs=prepared_params.function_tools,
                                allow_text_output=prepared_params.allow_text_output,
                                allow_parallel_tool_calls=allow_parallel_tool_calls(
                                    messages=messages,
                                    discovery_tool_names=self._discovery_tool_names,
                                ),
                                profile=self.profile_name,
                                tool_approvals=self._tool_approvals,
                                extra_input_properties=self._extra_input_properties,
                            )
                            result = await asyncio.to_thread(
                                call_with_optional_meta,
                                self._client.language_chat_with_tools,
                                meta=request_meta,
                                inference_request=inference_request,
                                timeout_seconds=self._timeout_seconds,
                            )
                            valid_tool_calls, invalid_tool_names = (
                                partition_returned_tool_calls(
                                    tool_calls=result.tool_calls,
                                    advertised_tool_names=(
                                        item.name
                                        for item in prepared_params.function_tools
                                    ),
                                )
                            )
                            if len(invalid_tool_names) == 0:
                                break
                            _LOGGER.warning(
                                "agent model returned unadvertised tool calls",
                                extra={
                                    "invalid_tool_names": list(invalid_tool_names),
                                    "advertised_tool_names": advertised_tool_names,
                                    "repair_attempt": repair_attempt + 1,
                                    "profile": self.profile_name,
                                },
                            )
                            if len(valid_tool_calls) > 0 or repair_attempt >= (
                                INVALID_TOOL_CALL_REPAIR_ATTEMPTS - 1
                            ):
                                break
                            system_blocks = (
                                *self._system_blocks,
                                InferenceSystemBlock(
                                    kind="instructions",
                                    text=INVALID_TOOL_CALL_RETRY_INSTRUCTION,
                                ),
                            )
                        assert result is not None
                        self.last_result = result
                        if len(valid_tool_calls) == 0 and len(invalid_tool_names) > 0:
                            raise BrainInternalError(
                                message=(
                                    "lms.chat_with_tools domain failure: model returned "
                                    "unadvertised tool call(s): "
                                    f"{', '.join(invalid_tool_names)}"
                                ),
                                operation="lms.chat_with_tools",
                                details=(
                                    SdkErrorDetail(
                                        code="INVALID_TOOL_CALL",
                                        message=(
                                            "model returned tool call(s) not present in "
                                            "the advertised tool list: "
                                            f"{', '.join(invalid_tool_names)}"
                                        ),
                                        category="internal",
                                        retryable=False,
                                        metadata={
                                            "tool_names": ",".join(invalid_tool_names)
                                        },
                                    ),
                                ),
                            )
                        parts: list[TextPart | ToolCallPart] = []
                        intermediate_text = (
                            result.text.strip() if result.text is not None else ""
                        )
                        if intermediate_text != "":
                            parts.append(TextPart(intermediate_text))
                        parts.extend(
                            to_model_tool_call(item) for item in valid_tool_calls
                        )
                        if len(parts) == 0:
                            parts.append(TextPart(_EMPTY_RESPONSE_FALLBACK))
                        if (
                            intermediate_text != ""
                            and len(valid_tool_calls) > 0
                            and self._operator_intermediate_text_notifier is not None
                        ):
                            await self._operator_intermediate_text_notifier(
                                client=self._client,
                                turn_state=self._turn_state,
                                session_id=self._session_id,
                                text=intermediate_text,
                                reasoning_level=self.profile_name,
                            )
                        self._last_used_profile_name = self.profile_name
                        set_current_span_attributes(
                            {
                                "brain.operation": "lms.chat_with_tools",
                                "brain.trace_id": request_meta.trace_id,
                                "brain.envelope_id": request_meta.envelope_id,
                                "brain.parent_id": request_meta.parent_id,
                                "brain.session_id": self._session_id,
                                "brain.principal": self._principal,
                                "brain.source": self._source,
                                "llm.provider": result.provider,
                                "llm.model": result.model,
                                "llm.profile": self.profile_name,
                                "llm.finish_reason": result.finish_reason,
                                "llm.tool_call_count": len(valid_tool_calls),
                                "llm.outcome": "success",
                            }
                        )
                        return ModelResponse(
                            parts=parts,
                            model_name=result.model,
                            provider_name=result.provider,
                            finish_reason=normalize_finish_reason(result.finish_reason),
                        )
                    except BrainSdkError as exc:
                        if not should_retry_language_failure(exc):
                            raise
                        last_exc = exc
                        is_last_provider_attempt = provider_attempt >= len(
                            LMS_PROVIDER_RETRY_DELAYS_SECONDS
                        )
                        should_notify = should_notify_operator_of_language_recovery(exc)
                        if (
                            should_notify
                            and self._operator_recovery_notifier is not None
                            and _recovery_notice_due(
                                profile_index=profile_index,
                                next_delay=(
                                    0.0
                                    if is_last_provider_attempt
                                    else LMS_PROVIDER_RETRY_DELAYS_SECONDS[
                                        provider_attempt
                                    ]
                                ),
                            )
                        ):
                            await self._operator_recovery_notifier(
                                client=self._client,
                                turn_state=self._turn_state,
                                session_id=self._session_id,
                                message=self._recovery_notice_message,
                                reasoning_level=self.profile_name,
                            )
                            self._turn_state.language_recovery_notice_sent = True
                        if is_last_provider_attempt:
                            break
                        retry_delay_seconds = (
                            LMS_PROVIDER_RETRY_DELAYS_SECONDS[provider_attempt]
                            if should_notify
                            else 0.0
                        )
                        if retry_delay_seconds > 0.0:
                            await asyncio.sleep(retry_delay_seconds)
                            cumulative_retry_delay_seconds += retry_delay_seconds
                        continue
            if last_exc is not None:
                raise last_exc
            raise BrainInternalError(
                message="lms.chat_with_tools domain failure: recovery exhausted",
                operation="lms.chat_with_tools",
            )
        finally:
            self.set_profile_name(original_profile_name)

    @property
    def model_name(self) -> str:
        """Return the stable local model identifier."""
        return "brain-sdk-lms"

    @property
    def system(self) -> str:
        """Return the provider/system identifier for telemetry purposes."""
        return "brain"

    @property
    def profile_name(self) -> str:
        """Return the active Language profile name for this agent turn."""
        value = getattr(self, "_profile_name", "")
        return value if isinstance(value, str) and value != "" else "standard"

    def set_profile_name(self, profile_name: str) -> None:
        """Update the active Language profile name for subsequent requests."""
        self._profile_name = profile_name

    @property
    def last_used_profile_name(self) -> str:
        """Return the profile that produced the latest successful model response."""
        value = getattr(self, "_last_used_profile_name", "")
        return value if isinstance(value, str) and value != "" else self.profile_name


def call_with_optional_meta(
    func: Callable[..., Any],
    /,
    *,
    meta: MetaOverrides | None,
    **kwargs: Any,
) -> Any:
    """Call one SDK-style method, forwarding only the arguments it accepts.

    Some test fakes do not accept ``meta`` as a keyword-only argument.
    This shim inspects the callable's signature and forwards ``meta``
    (and other keyword arguments) only when the callable declares them,
    so the model works correctly against both real and fake clients.
    """
    try:
        signature = inspect.signature(func)
        parameters = signature.parameters
    except TypeError, ValueError:
        return func(meta=meta, **kwargs)
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    filtered_kwargs = (
        kwargs
        if accepts_kwargs
        else {key: value for key, value in kwargs.items() if key in parameters}
    )
    if "meta" in parameters or accepts_kwargs:
        return func(meta=meta, **filtered_kwargs)
    return func(**filtered_kwargs)


__all__ = [
    "AgentToolModel",
    "OperatorIntermediateTextNotifier",
    "OperatorRecoveryNotifier",
    "call_with_optional_meta",
]
