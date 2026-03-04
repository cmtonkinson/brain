"""Runtime entrypoint for the long-lived Brain Agent container."""

from __future__ import annotations

import json
import logging
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import Agent, Tool
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from packages.brain_sdk import (
    BrainClient,
    BrainSdkConfig,
    CapabilityDescriptor,
    LmsChatResult,
    MemoryContextBlock,
    SwitchboardOperatorInstruction,
)
from packages.brain_shared.config import load_actor_settings

_LOGGER = logging.getLogger(__name__)
_RUNNING = True
_LONG_POLL_BUFFER_SECONDS = 1.0
_MIN_LONG_POLL_SECONDS = 1.0
_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_SYSTEM_PROMPT_PATH = _PROMPTS_DIR / "system.txt"


@dataclass(slots=True)
class _TurnState:
    """Mutable turn-local metadata shared by capability tool wrappers."""

    actor: str = "operator"
    channel: str = ""


@dataclass(frozen=True, slots=True)
class _ParsedModelOutput:
    """Normalized structured output parsed from one LMS chat response."""

    kind: str
    content: str = ""
    tool_name: str = ""
    input_payload: dict[str, object] | None = None


@dataclass(slots=True)
class _AgentRuntime:
    """Assembled agent runtime dependencies created once at startup."""

    client: BrainClient
    session_id: str
    turn_state: _TurnState
    model_driver: "_BrainSdkModelDriver"
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


class _BrainSdkModelDriver:
    """Function-model bridge that delegates model reasoning to the Brain SDK LMS."""

    def __init__(self, *, client: BrainClient) -> None:
        self._client = client
        self.last_chat_result: LmsChatResult | None = None

    def run_model(
        self,
        messages: list[ModelRequest | ModelResponse],
        info: AgentInfo,
    ) -> ModelResponse:
        """Convert PydanticAI state into an LMS prompt and normalize the reply."""
        prompt = self._build_prompt(messages=messages, info=info)
        chat = self._client.lms_chat(prompt=prompt, profile="standard")
        self.last_chat_result = chat
        parsed = _parse_model_output(chat.text)
        if parsed.kind == "tool_call" and parsed.tool_name in {
            tool.name for tool in info.function_tools
        }:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=parsed.tool_name,
                        args={
                            "input_payload": {}
                            if parsed.input_payload is None
                            else parsed.input_payload
                        },
                    )
                ],
                model_name=chat.model,
                provider_name=chat.provider,
            )
        if parsed.kind == "final" and parsed.content.strip() != "":
            text = parsed.content.strip()
        else:
            text = chat.text.strip()
        if text == "":
            text = "I do not have a response yet."
        return ModelResponse(
            parts=[TextPart(text)],
            model_name=chat.model,
            provider_name=chat.provider,
        )

    def _build_prompt(
        self,
        *,
        messages: list[ModelRequest | ModelResponse],
        info: AgentInfo,
    ) -> str:
        """Render one deterministic prompt for the SDK-backed LMS call."""
        tool_lines = []
        for tool in info.function_tools:
            schema = json.dumps(tool.parameters_json_schema, sort_keys=True)
            description = "" if tool.description is None else tool.description
            tool_lines.append(f"- {tool.name}: {description}\n  schema: {schema}")
        transcript_lines = []
        for message in messages:
            transcript_lines.extend(_render_model_message(message))
        sections = [
            "You are choosing the next agent action.",
            _load_system_prompt(),
        ]
        if info.instructions:
            sections.append(f"Runtime instructions:\n{info.instructions}")
        sections.append(
            "Available tools:\n"
            + ("\n".join(tool_lines) if tool_lines else "(no tools available)")
        )
        sections.append(
            "Conversation state:\n"
            + ("\n".join(transcript_lines) if transcript_lines else "(empty)")
        )
        sections.append(
            "Return JSON only. Prefer a tool call when external state or actions are needed."
        )
        return "\n\n".join(sections)


def _render_model_message(message: ModelRequest | ModelResponse) -> list[str]:
    """Render one PydanticAI message into stable plain-text transcript lines."""
    lines: list[str] = []
    for part in message.parts:
        part_kind = getattr(part, "part_kind", "")
        if part_kind == "system-prompt":
            lines.append(f"system: {getattr(part, 'content', '')}")
        elif part_kind == "user-prompt":
            lines.append(f"user: {_stringify_content(getattr(part, 'content', ''))}")
        elif part_kind == "tool-return":
            lines.append(
                f"tool-result {getattr(part, 'tool_name', '')}: "
                f"{_stringify_content(getattr(part, 'content', ''))}"
            )
        elif part_kind == "retry-prompt":
            lines.append(f"retry: {_stringify_content(getattr(part, 'content', ''))}")
        elif part_kind == "tool-call":
            lines.append(
                f"tool-call {getattr(part, 'tool_name', '')}: "
                f"{_stringify_content(getattr(part, 'args', ''))}"
            )
        elif part_kind == "text":
            lines.append(f"assistant: {getattr(part, 'content', '')}")
    return lines


def _stringify_content(value: object) -> str:
    """Render one structured content value into a stable compact string."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)


def _parse_model_output(text: str) -> _ParsedModelOutput:
    """Parse one LMS response into a tool-call or final-answer instruction."""
    try:
        payload = json.loads(text)
    except ValueError:
        return _ParsedModelOutput(kind="final", content=text)
    if not isinstance(payload, dict):
        return _ParsedModelOutput(kind="final", content=text)
    kind = str(payload.get("kind", "")).strip()
    if kind == "tool_call":
        tool_name = str(payload.get("tool_name", "")).strip()
        input_payload = payload.get("input_payload", {})
        if tool_name != "" and isinstance(input_payload, dict):
            return _ParsedModelOutput(
                kind="tool_call",
                tool_name=tool_name,
                input_payload=dict(input_payload),
            )
    if kind == "final":
        content = str(payload.get("content", "")).strip()
        if content != "":
            return _ParsedModelOutput(kind="final", content=content)
    return _ParsedModelOutput(kind="final", content=text)


def _build_capability_tools(
    *,
    client: BrainClient,
    capabilities: tuple[CapabilityDescriptor, ...],
    turn_state: _TurnState,
) -> list[Tool[None]]:
    """Create one PydanticAI tool wrapper per active Capability."""
    tools: list[Tool[None]] = []
    for descriptor in capabilities:
        input_schema = (
            ""
            if descriptor.input_schema is None
            else json.dumps(descriptor.input_schema, sort_keys=True)
        )
        summary = descriptor.summary.strip()
        description = summary
        if input_schema != "":
            description = f"{summary} Input schema: {input_schema}"

        def _invoke(
            input_payload: dict[str, object],
            *,
            _capability_id: str = descriptor.capability_id,
        ) -> object:
            result = client.invoke_capability(
                capability_id=_capability_id,
                input_payload=input_payload,
                actor=turn_state.actor,
                channel=turn_state.channel,
            )
            return result.output

        tools.append(
            Tool(
                _invoke,
                name=descriptor.capability_id,
                description=description,
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
    model_driver = _BrainSdkModelDriver(client=client)
    agent = Agent(
        FunctionModel(model_driver.run_model, model_name="brain-sdk-lms"),
        system_prompt=_load_system_prompt(),
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
        model_driver=model_driver,
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


def _process_instruction(
    *,
    runtime: _AgentRuntime,
    instruction: SwitchboardOperatorInstruction,
) -> str:
    """Handle one inbound operator instruction end-to-end."""
    context = runtime.client.memory_assemble_context(
        session_id=runtime.session_id,
        message=instruction.message_text,
    )
    runtime.turn_state.actor = "operator"
    runtime.turn_state.channel = instruction.source
    runtime.model_driver.last_chat_result = None
    result = runtime.agent.run_sync(
        _format_user_prompt(instruction=instruction, context=context)
    )
    response_text = str(result.output).strip()
    if response_text == "":
        response_text = "I do not have a response yet."
    chat = runtime.model_driver.last_chat_result
    runtime.client.memory_record_response(
        session_id=runtime.session_id,
        content=response_text,
        model="brain-sdk-lms" if chat is None else chat.model,
        provider="brain-sdk" if chat is None else chat.provider,
        token_count=_estimate_token_count(response_text),
        reasoning_level="standard",
    )
    return response_text


def main() -> None:
    """Run the long-lived Brain Agent process."""
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
                instruction = runtime.client.switchboard_poll_operator_instruction(
                    wait_timeout_seconds=wait_timeout_seconds
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
                response_text = _process_instruction(
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
                time.sleep(1.0)
    finally:
        client.close()
        _LOGGER.info("brain agent stopped")


if __name__ == "__main__":
    main()
