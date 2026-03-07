"""Runtime entrypoint for the long-lived Brain Agent container."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import Agent, Tool
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.tools import ToolDefinition

from packages.brain_sdk import (
    BrainClient,
    BrainDependencyError,
    BrainSdkConfig,
    CapabilityDescriptor,
    LmsChatMessage,
    LmsChatToolCall,
    LmsChatToolDefinition,
    LmsToolChatResult,
    MemoryContextBlock,
    SwitchboardOperatorInstruction,
)
from packages.brain_shared.config import load_actor_settings

_LOGGER = logging.getLogger(__name__)
_RUNNING = True
_LONG_POLL_BUFFER_SECONDS = 1.0
_MIN_LONG_POLL_SECONDS = 1.0
_LMS_THROTTLE_RESPONSE = (
    "I'm temporarily rate limited by the language model provider. "
    "Please try again in a minute."
)
_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_SYSTEM_PROMPT_PATH = _PROMPTS_DIR / "system.txt"


@dataclass(slots=True)
class _TurnState:
    """Mutable turn-local metadata shared by capability tool wrappers."""

    actor: str = "operator"
    channel: str = ""


@dataclass(slots=True)
class _AgentRuntime:
    """Assembled agent runtime dependencies created once at startup."""

    client: BrainClient
    session_id: str
    turn_state: _TurnState
    model: "_BrainSdkToolModel"
    agent: Agent[None, str]


def _handle_shutdown(_signum: int, _frame: object) -> None:
    """Mark the agent runtime for graceful shutdown."""
    global _RUNNING
    _RUNNING = False


def _resolve_config_path() -> Path | None:
    """Return an explicit actors config path when the env override is set."""
    value = os.getenv("BRAIN_ACTORS_CONFIG_FILE", "").strip()
    if value == "":
        return None
    return Path(value)


def _load_system_prompt() -> str:
    """Load the agent system prompt from the colocated prompt file."""
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _configure_logging(*, level: str) -> None:
    """Install a minimal process-local logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class _BrainSdkToolModel(Model):
    """PydanticAI model backed by the Brain SDK tool-capable LMS endpoint."""

    def __init__(self, *, client: BrainClient, profile_name: str = "standard") -> None:
        super().__init__(profile=ModelProfile(supports_tools=True))
        self._client = client
        self._profile_name = profile_name
        self.last_result: LmsToolChatResult | None = None

    async def request(
        self,
        messages: list[ModelRequest | ModelResponse],
        model_settings: object,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Request one tool-capable model response from the SDK-backed LMS."""
        del model_settings
        prepared_settings, prepared_params = self.prepare_request(
            None, model_request_parameters
        )
        del prepared_settings
        result = await asyncio.to_thread(
            self._client.lms_chat_with_tools,
            messages=tuple(_to_sdk_messages(messages)),
            tools=tuple(
                _to_sdk_tool_definition(item) for item in prepared_params.function_tools
            ),
            allow_text_output=prepared_params.allow_text_output,
            profile=self._profile_name,
        )
        self.last_result = result
        parts: list[TextPart | ToolCallPart] = []
        if result.text is not None and result.text.strip() != "":
            parts.append(TextPart(result.text.strip()))
        parts.extend(_to_model_tool_call(item) for item in result.tool_calls)
        if len(parts) == 0:
            parts.append(TextPart("I do not have a response yet."))
        return ModelResponse(
            parts=parts,
            model_name=result.model,
            provider_name=result.provider,
            finish_reason=_normalize_finish_reason(result.finish_reason),
        )

    @property
    def model_name(self) -> str:
        """Return the stable local model identifier."""
        return "brain-sdk-lms"

    @property
    def system(self) -> str:
        """Return the provider/system identifier for telemetry purposes."""
        return "brain"


def _stringify_content(value: object) -> str:
    """Render one structured content value into a stable compact string."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)


def _to_sdk_messages(
    messages: list[ModelRequest | ModelResponse],
) -> list[LmsChatMessage]:
    """Convert PydanticAI message history into SDK LMS chat messages."""
    result: list[LmsChatMessage] = []
    for message in messages:
        result.extend(_to_sdk_message_parts(message))
    return result


def _to_sdk_message_parts(
    message: ModelRequest | ModelResponse,
) -> list[LmsChatMessage]:
    """Convert one PydanticAI message into one or more SDK LMS messages."""
    if isinstance(message, ModelRequest):
        result: list[LmsChatMessage] = []
        for part in message.parts:
            if isinstance(part, SystemPromptPart):
                result.append(LmsChatMessage(role="system", content=part.content))
            elif isinstance(part, UserPromptPart):
                result.append(
                    LmsChatMessage(
                        role="user",
                        content=_stringify_content(part.content),
                    )
                )
            elif isinstance(part, ToolReturnPart):
                result.append(
                    LmsChatMessage(
                        role="tool",
                        content=_stringify_content(part.content),
                        tool_name=part.tool_name,
                        tool_call_id=part.tool_call_id,
                    )
                )
            else:
                result.append(
                    LmsChatMessage(
                        role="user",
                        content=_stringify_content(getattr(part, "content", "")),
                    )
                )
        return result

    text_parts: list[str] = []
    tool_calls: list[LmsChatToolCall] = []
    for part in message.parts:
        if isinstance(part, TextPart):
            text_parts.append(part.content)
        elif isinstance(part, ToolCallPart):
            tool_calls.append(
                LmsChatToolCall(
                    tool_name=part.tool_name,
                    args_json=_tool_args_json(part.args),
                    tool_call_id=part.tool_call_id,
                )
            )
    if len(text_parts) == 0 and len(tool_calls) == 0:
        return []
    return [
        LmsChatMessage(
            role="assistant",
            content="\n".join(part for part in text_parts if part != ""),
            tool_calls=tuple(tool_calls),
        )
    ]


def _tool_args_json(value: str | dict[str, object] | None) -> str:
    """Convert one tool-call args payload into canonical JSON text."""
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def _to_sdk_tool_definition(value: ToolDefinition) -> LmsChatToolDefinition:
    """Convert one PydanticAI tool definition into an SDK LMS tool definition."""
    return LmsChatToolDefinition(
        name=value.name,
        parameters_json_schema=dict(value.parameters_json_schema),
        description=value.description,
        strict=value.strict,
        sequential=value.sequential,
    )


def _to_model_tool_call(value: LmsChatToolCall) -> ToolCallPart:
    """Convert one SDK LMS tool call into a PydanticAI response part."""
    return ToolCallPart(
        tool_name=value.tool_name,
        args=_decode_tool_args_json(value.args_json),
        tool_call_id=value.tool_call_id,
    )


def _decode_tool_args_json(value: str) -> str | dict[str, object]:
    """Decode canonical tool args JSON into dict form when valid."""
    try:
        payload = json.loads(value)
    except ValueError:
        return value
    if isinstance(payload, dict):
        return payload
    return value


def _normalize_finish_reason(value: str) -> str | None:
    """Normalize LMS finish reasons into the subset PydanticAI expects."""
    if value in {"stop", "length", "content_filter", "tool_call", "error"}:
        return value
    return None


def _build_capability_tools(
    *,
    client: BrainClient,
    capabilities: tuple[CapabilityDescriptor, ...],
    turn_state: _TurnState,
) -> list[Tool[None]]:
    """Create one PydanticAI tool wrapper per active Capability."""
    tools: list[Tool[None]] = []
    for descriptor in capabilities:
        summary = descriptor.summary.strip()
        description = summary
        input_schema = (
            {"type": "object", "properties": {}, "additionalProperties": False}
            if descriptor.input_schema is None
            else dict(descriptor.input_schema)
        )

        def _invoke(
            _capability_id: str = descriptor.capability_id,
            **input_payload: object,
        ) -> object:
            result = client.invoke_capability(
                capability_id=_capability_id,
                input_payload=input_payload,
                actor=turn_state.actor,
                channel=turn_state.channel,
            )
            return result.output

        tools.append(
            Tool.from_schema(
                _invoke,
                name=descriptor.capability_id,
                description=description,
                json_schema=input_schema,
            )
        )
    return tools


def _brain_sdk_config_from_settings(settings: object) -> BrainSdkConfig:
    """Project actor settings into the SDK client configuration model."""
    return BrainSdkConfig(
        socket_path=str(settings.core.socket_path),
        timeout_seconds=float(settings.core.timeout_seconds),
        source=str(settings.agent.source),
        principal=str(settings.agent.principal),
    )


def _create_runtime(*, client: BrainClient) -> _AgentRuntime:
    """Create one fully wired agent runtime from the published Core surface."""
    session = client.memory_get_latest_or_create_session()
    capabilities = client.describe_capabilities()
    turn_state = _TurnState()
    model = _BrainSdkToolModel(client=client)
    agent = Agent(
        model,
        system_prompt=_load_system_prompt(),
        retries=3,
        max_concurrency=1,
        tools=_build_capability_tools(
            client=client,
            capabilities=capabilities,
            turn_state=turn_state,
        ),
    )
    return _AgentRuntime(
        client=client,
        session_id=session.session_id,
        turn_state=turn_state,
        model=model,
        agent=agent,
    )


def _long_poll_timeout_seconds(*, sdk_timeout_seconds: float) -> float:
    """Choose one bounded long-poll timeout that stays under the HTTP timeout."""
    return max(_MIN_LONG_POLL_SECONDS, sdk_timeout_seconds - _LONG_POLL_BUFFER_SECONDS)


def _format_user_prompt(
    *,
    instruction: SwitchboardOperatorInstruction,
    context: MemoryContextBlock,
) -> str:
    """Render one full prompt from MAS context plus inbound message metadata."""
    dialogue_lines = [f"- {turn.role}: {turn.content}" for turn in context.dialogue]
    snippet_lines = [f"- {snippet}" for snippet in context.reference_snippets]
    return "\n".join(
        [
            "Operator Instruction",
            f"channel: {instruction.source}",
            f"sender: {instruction.sender_e164}",
            f"message: {instruction.message_text}",
            "",
            "MAS Context",
            f"operator_name: {context.profile.operator_name}",
            f"brain_name: {context.profile.brain_name}",
            f"brain_verbosity: {context.profile.brain_verbosity}",
            f"focus: {'' if context.focus is None else context.focus}",
            "dialogue:",
            *(dialogue_lines or ["- (none)"]),
            "reference_snippets:",
            *(snippet_lines or ["- (none)"]),
        ]
    )


def _estimate_token_count(text: str) -> int:
    """Estimate token count with the same simple heuristic MAS uses internally."""
    words = len([item for item in text.split() if item])
    if words <= 0:
        return 0
    estimated = words * 3
    return (estimated + 1) // 2


def _is_retryable_lms_throttle(exc: BrainDependencyError) -> bool:
    """Return True when one LMS dependency failure represents provider throttling."""
    if exc.operation not in {"lms.chat", "lms.chat_with_tools"}:
        return False
    if not any(detail.retryable for detail in exc.details):
        return False
    message = str(exc).lower()
    throttle_tokens = ("rate limit", "rate_limit", "throttle", "too many requests")
    return any(token in message for token in throttle_tokens)


async def _process_instruction(
    *,
    runtime: _AgentRuntime,
    instruction: SwitchboardOperatorInstruction,
) -> str:
    """Handle one inbound operator instruction end-to-end."""
    context = await asyncio.to_thread(
        runtime.client.memory_assemble_context,
        session_id=runtime.session_id,
        message=instruction.message_text,
    )
    runtime.turn_state.actor = "operator"
    runtime.turn_state.channel = instruction.source
    runtime.model.last_result = None
    try:
        result = await runtime.agent.run(
            _format_user_prompt(instruction=instruction, context=context)
        )
        response_text = str(result.output).strip()
        if response_text == "":
            response_text = "I do not have a response yet."
    except BrainDependencyError as exc:
        if not _is_retryable_lms_throttle(exc):
            raise
        _LOGGER.warning(
            "brain agent lms throttled; returning fallback response",
            extra={"operation": exc.operation},
        )
        response_text = _LMS_THROTTLE_RESPONSE
    chat = runtime.model.last_result
    await asyncio.to_thread(
        runtime.client.memory_record_response,
        session_id=runtime.session_id,
        content=response_text,
        model="brain-sdk-lms" if chat is None else chat.model,
        provider="brain-sdk" if chat is None else chat.provider,
        token_count=_estimate_token_count(response_text),
        reasoning_level="standard",
    )
    await _route_outbound_response(
        runtime=runtime,
        instruction=instruction,
        response_text=response_text,
    )
    return response_text


async def _route_outbound_response(
    *,
    runtime: _AgentRuntime,
    instruction: SwitchboardOperatorInstruction,
    response_text: str,
) -> None:
    """Deliver one finalized response via Attention Router notify capability."""
    payload: dict[str, object] = {
        "actor": "operator",
        "channel": instruction.source,
        "message": response_text,
    }
    recipient = instruction.sender_e164.strip()
    if recipient != "":
        payload["recipient_e164"] = recipient
    try:
        await asyncio.to_thread(
            runtime.client.invoke_capability,
            capability_id="attention-notify",
            input_payload=payload,
            actor="operator",
            channel=instruction.source,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "brain agent outbound notify failed",
            extra={
                "capability_id": "attention-notify",
                "channel": instruction.source,
                "recipient_e164": instruction.sender_e164,
            },
        )


async def _run_main() -> None:
    """Run the long-lived Brain Agent process inside one event loop."""
    global _RUNNING
    _RUNNING = True

    settings = load_actor_settings(config_path=_resolve_config_path())
    _configure_logging(level=str(settings.logging.level))

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    client = BrainClient(config=_brain_sdk_config_from_settings(settings))
    try:
        runtime = _create_runtime(client=client)
        _LOGGER.info(
            "brain agent started",
            extra={
                "socket_path": settings.core.socket_path,
                "timeout_seconds": settings.core.timeout_seconds,
                "source": settings.agent.source,
                "principal": settings.agent.principal,
                "session_id": runtime.session_id,
            },
        )
        wait_timeout_seconds = _long_poll_timeout_seconds(
            sdk_timeout_seconds=settings.core.timeout_seconds
        )
        while _RUNNING:
            try:
                instruction = await asyncio.to_thread(
                    runtime.client.switchboard_poll_operator_instruction,
                    wait_timeout_seconds=wait_timeout_seconds,
                )
                if instruction is None:
                    continue
                _LOGGER.debug(
                    "brain agent received instruction",
                    extra={
                        "channel": instruction.source,
                        "sender_e164": instruction.sender_e164,
                        "message_text": instruction.message_text,
                    },
                )
                response_text = await _process_instruction(
                    runtime=runtime,
                    instruction=instruction,
                )
                _LOGGER.info(
                    "brain agent completed turn",
                    extra={
                        "channel": instruction.source,
                        "sender_e164": instruction.sender_e164,
                        "response": response_text,
                    },
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("brain agent turn failed")
                await asyncio.sleep(1.0)
    finally:
        client.close()
        _LOGGER.info("brain agent stopped")


def main() -> None:
    """Run the long-lived Brain Agent process."""
    asyncio.run(_run_main())


if __name__ == "__main__":
    main()
