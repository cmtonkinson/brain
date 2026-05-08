"""Runtime entrypoint for the long-lived Brain Assistant container."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from pydantic_ai import Agent
from pydantic_ai.messages import CachePoint, UserContent
from lib.agent import (
    is_retryable_language_throttle,
    is_retryable_language_timeout,
    is_retryable_language_transport_timeout,
)
from lib.agent.history import estimate_token_count
from lib.agent.tool_model import AgentToolModel, call_with_optional_meta
from lib.agent.toolset import filtered_brain_toolset
from lib.agent.turn_state import (
    DefaultTurnState,
    GET_TOOL_INFO_TOOL_NAME,
    MAX_PENDING_INVOCATIONS,
    PendingInvocation,
    SEARCH_TOOLS_TOOL_NAME,
)
from lib.sdk import (
    BrainClient,
    BrainDependencyError,
    BrainDomainError,
    BrainSdkConfig,
    BrainTransportError,
    MemoryContextBlock,
    RelayOperatorInstruction,
    ToolSystemHint,
    render_system_prompt_blocks,
    render_system_tool_hints,
)
from lib.sdk.environment import assemble_environment_context
from lib.sdk.errors import BrainSdkError
from lib.shared.config import (
    ActorSettings,
    CoreRuntimeSettings,
    CoreSettings,
    component_settings_for,
    load_actor_settings,
    load_core_runtime_settings,
)

from lib.shared.language_model import (
    ConversationSummaryContentPart,
    DialogueTurnContentPart,
    EnvironmentContextContentPart,
    FocusContentPart,
    InferenceEnvironmentContext,
    InferenceSystemBlock,
    OperatorMessageContentPart,
    ReferenceSnippetContentPart,
)
from lib.shared.observability import (
    bootstrap_observability,
    is_observability_enabled,
    set_current_span_attributes,
    set_span_attributes,
)
from resources.adapters.llm.config import (
    max_retry_budget_seconds,
    resolve_llm_adapter_settings,
)

_LOGGER = logging.getLogger(__name__)
_RUNNING = True
_LONG_POLL_BUFFER_SECONDS = 1.0
_MIN_LONG_POLL_SECONDS = 1.0
_LMS_THROTTLE_RESPONSE = (
    "I'm temporarily rate limited by the language model provider. "
    "Please try again in a minute."
)
_LMS_TIMEOUT_RESPONSE = (
    "I'm temporarily having trouble reaching the language model provider. "
    "Please try again in a minute."
)
_LMS_GENERIC_ERROR_RESPONSE = (
    "I hit an internal language-model error while working on that. Please try again."
)
_LMS_RECOVERY_IN_PROGRESS_RESPONSE = (
    "I'm sorry, but the language model provider is having trouble. "
    "I'm still working on it and will keep trying."
)
_INTERMEDIATE_TEXT_FORMAT = "_… {text}…_"
"""Operator-channel rendering for model commentary that accompanies tool calls.

A single horizontal-ellipsis glyph (U+2026) plus Markdown italics signals
that the surfaced text is interim chain-of-thought rather than a final
operator-directed reply.
"""
_LMS_TIMEOUT_MARGIN_SECONDS = 2.0
_AGENT_DIR = Path(__file__).resolve().parent
_PROMPTS_DIR = _AGENT_DIR / "prompts"
_COMPRESS_SYSTEM_PROMPT_PATH = _PROMPTS_DIR / "compress-tool-return.txt"
_COMPRESS_USER_PROMPT_TEMPLATE_PATH = (
    _PROMPTS_DIR / "compress-tool-return-user-template.txt"
)
_AGENT_CONTEXT_PROPERTIES_PATH = _AGENT_DIR / "tool-context-properties.json"
_SEARCH_TOOLS_TOOL_NAME = SEARCH_TOOLS_TOOL_NAME
_GET_TOOL_INFO_TOOL_NAME = GET_TOOL_INFO_TOOL_NAME
_MAX_PENDING_INVOCATIONS = MAX_PENDING_INVOCATIONS
_HEARTBEAT_FILE_ENV = "BRAIN_ASSISTANT_HEARTBEAT_FILE"
_HEARTBEAT_PATH = Path("/run/brain/assistant-heartbeat")
_DISCOVERY_TOOL_NAMES = frozenset({_SEARCH_TOOLS_TOOL_NAME, _GET_TOOL_INFO_TOOL_NAME})
# PydanticAI retries on invalid tool call responses.
_AGENT_TOOL_CALL_RETRIES = 3
# Tool calls execute sequentially; parallelism is managed per-hop via prepare_tools.
_AGENT_MAX_CONCURRENCY = 1
# Brief pause after a turn exception before resuming the poll loop.
_TURN_FAILURE_BACKOFF_SECONDS = 1.0
_RELAY_NOTIFY_OP_ID = "relay-notify"


def _json_dumps_or_empty(value: object | None) -> str:
    """Serialize one value for Langfuse JSON-string observation fields."""
    if value is None:
        return ""
    return json.dumps(value, sort_keys=True, default=str)


def _operator_observation_input(
    *,
    system_blocks: tuple[InferenceSystemBlock, ...],
    instruction: RelayOperatorInstruction,
) -> dict[str, object]:
    """Return the Langfuse-facing root turn input payload."""
    payload: dict[str, object] = {
        "message": _instruction_context_message(instruction),
        "channel": instruction.source,
        "system_prompt": _system_blocks_for_observation(system_blocks),
    }
    if instruction.sender_e164 != "":
        payload["sender_e164"] = instruction.sender_e164
    if instruction.approval_intent is not None:
        payload["approval_intent"] = instruction.approval_intent
    if instruction.reaction_emoji is not None:
        payload["reaction_emoji"] = instruction.reaction_emoji
    return payload


def _system_blocks_for_observation(
    blocks: tuple[InferenceSystemBlock, ...],
) -> str:
    """Render canonical system blocks into one stable observation string."""
    return "\n\n".join(
        f"<{block.kind}>\n{block.text}\n</{block.kind}>"
        for block in blocks
        if block.text != ""
    )


class _AgentTurnObservation:
    """Context manager for one Langfuse-compatible Agent turn span."""

    def __init__(
        self,
        *,
        runtime: "_AgentRuntime",
        instruction: RelayOperatorInstruction,
    ) -> None:
        self._runtime = runtime
        self._instruction = instruction
        self._span: object | None = None

    def __enter__(self) -> object | None:
        """Start the root turn span when process observability is active."""
        if not is_observability_enabled():
            return None
        try:
            from opentelemetry import trace
        except ImportError:
            return None

        tracer = trace.get_tracer("brain.assistant")
        manager = tracer.start_as_current_span("assistant.turn")
        span = manager.__enter__()
        self._manager = manager
        self._span = span
        observation_input = _operator_observation_input(
            system_blocks=self._runtime.system_blocks,
            instruction=self._instruction,
        )
        input_json = _json_dumps_or_empty(observation_input)
        set_span_attributes(
            span,
            {
                "langfuse.observation.type": "span",
                "langfuse.trace.name": "brain.turn",
                "langfuse.user.id": self._runtime.turn_state.actor,
                "langfuse.session.id": self._runtime.session_id,
                "langfuse.observation.input": input_json,
                "langfuse.trace.input": input_json,
                "langfuse.trace.metadata.brain_trace_id": self._runtime.turn_state.trace_id,
                "langfuse.trace.metadata.brain_envelope_id": self._runtime.turn_state.root_envelope_id,
                "langfuse.trace.metadata.brain_source": self._instruction.source,
                "langfuse.trace.metadata.mas_session_id": self._runtime.session_id,
                "langfuse.observation.metadata.operation": "assistant.turn",
                "brain.operation": "assistant.turn",
                "brain.trace_id": self._runtime.turn_state.trace_id,
                "brain.envelope_id": self._runtime.turn_state.root_envelope_id,
                "brain.session_id": self._runtime.session_id,
                "brain.principal": self._runtime.turn_state.actor,
                "brain.source": self._instruction.source,
            },
        )
        return span

    def __exit__(self, exc_type, exc, traceback) -> bool:
        """Finish the root turn span and preserve raised exceptions."""
        span = self._span
        if span is not None and exc is not None:
            record_exception = getattr(span, "record_exception", None)
            if callable(record_exception):
                record_exception(exc)
            set_span_attributes(
                span,
                {
                    "langfuse.observation.level": "ERROR",
                    "langfuse.observation.status_message": str(exc),
                    "langfuse.observation.metadata.outcome": "error",
                },
            )
        manager = getattr(self, "_manager", None)
        if manager is not None:
            return bool(manager.__exit__(exc_type, exc, traceback))
        return False


def _update_agent_turn_observation_session(
    *,
    span: object | None,
    runtime: "_AgentRuntime",
) -> None:
    """Attach Recall-resolved session identifiers to the root turn span."""
    if span is None:
        return
    session_id = runtime.turn_state.conversation_episode_id or runtime.session_id
    set_span_attributes(
        span,
        {
            "langfuse.session.id": session_id,
            "langfuse.trace.metadata.mas_session_id": runtime.session_id,
            "langfuse.trace.metadata.conversation_episode_id": runtime.turn_state.conversation_episode_id,
            "brain.session_id": runtime.session_id,
            "brain.conversation_episode_id": runtime.turn_state.conversation_episode_id,
        },
    )


def _complete_agent_turn_observation(
    *,
    span: object | None,
    response_text: str,
) -> None:
    """Attach the final Agent response to the root turn span."""
    if span is None:
        return
    output_json = _json_dumps_or_empty({"response": response_text})
    set_span_attributes(
        span,
        {
            "langfuse.observation.output": output_json,
            "langfuse.trace.output": output_json,
            "langfuse.observation.metadata.outcome": "success",
        },
    )


def _load_prompt_file(path: Path) -> str:
    """Load one prompt text file from disk without altering its contents."""
    return path.read_text(encoding="utf-8")


def _load_agent_context_properties(
    *, path: Path = _AGENT_CONTEXT_PROPERTIES_PATH
) -> dict[str, object]:
    """Load agent-only tool schema properties from the colocated JSON file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


_AGENT_CONTEXT_PROPERTIES = _load_agent_context_properties()
_COMPRESS_SYSTEM_PROMPT = _load_prompt_file(_COMPRESS_SYSTEM_PROMPT_PATH)
_COMPRESS_USER_PROMPT_TEMPLATE = _load_prompt_file(_COMPRESS_USER_PROMPT_TEMPLATE_PATH)


_PendingInvocation = PendingInvocation
_TurnState = DefaultTurnState


@dataclass(slots=True)
class _AgentRuntime:
    """Assembled agent runtime dependencies created once at startup."""

    client: BrainClient
    session_id: str
    turn_state: _TurnState
    model: AgentToolModel
    agent: Agent[None, str]
    language_request_timeout_seconds: float
    preferred_timezone: str = "UTC"
    system_blocks: tuple[InferenceSystemBlock, ...] = ()
    environment_context_entries: tuple[object, ...] = ()


def _handle_shutdown(_signum: int, _frame: object) -> None:
    """Mark the agent runtime for graceful shutdown."""
    global _RUNNING
    _RUNNING = False


def _resolve_config_dir() -> Path | None:
    """Return an explicit Brain config directory when the env override is set."""
    value = os.getenv("BRAIN_CONFIG_DIR", "").strip()
    if value == "":
        return None
    return Path(value)


def _resolve_config_path() -> Path | None:
    """Return the explicit Brain config directory path."""
    return _resolve_config_dir()


def _resolve_core_config_path() -> Path | None:
    """Return the explicit Brain config directory path."""
    return _resolve_config_dir()


def _resolve_resources_config_path() -> Path | None:
    """Return the explicit Brain config directory path."""
    return _resolve_config_dir()


def _load_startup_settings() -> tuple[ActorSettings, CoreRuntimeSettings]:
    """Load actor and core/resources settings using one optional config directory."""
    config_dir = _resolve_config_dir()
    settings = load_actor_settings(config_path=config_dir)
    core_runtime_settings = load_core_runtime_settings(
        core_config_path=config_dir,
    )
    return settings, core_runtime_settings


def _resolve_heartbeat_path() -> Path:
    """Return the heartbeat file path used by container health checks."""
    value = os.getenv(_HEARTBEAT_FILE_ENV, "").strip()
    if value == "":
        return _HEARTBEAT_PATH
    return Path(value)


def _write_heartbeat(*, path: Path | None = None) -> None:
    """Touch the heartbeat file to indicate the agent event loop is alive."""
    heartbeat_path = _resolve_heartbeat_path() if path is None else path
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.touch()


def _configure_logging(*, settings: ActorSettings) -> None:
    """Install shared dual-path logging for the long-lived agent process."""
    from lib.shared.logging import configure_logging

    process_name = settings.logging.process_name or "assistant"
    configure_logging(
        level=str(settings.logging.level),
        file_capture_enabled=settings.logging.file_capture_enabled,
        file_capture_level=str(settings.logging.file_capture_level),
        file_capture_directory=settings.logging.file_capture_directory,
        json_output=bool(settings.logging.json_output),
        process_name=process_name,
        environment=str(settings.logging.environment),
    )


def _sdk_config_from_settings(settings: ActorSettings) -> BrainSdkConfig:
    """Project actor settings into the SDK client configuration model."""
    return BrainSdkConfig(
        host=str(settings.core.host),
        port=int(settings.core.port),
        timeout_seconds=float(settings.core.timeout_seconds),
        source=str(settings.agent.source),
        principal=str(settings.agent.principal),
    )


def _derive_language_request_timeout_seconds(core_runtime_settings) -> float:
    """Return one derived agent->core timeout for Language chat requests only."""
    adapter_settings = resolve_llm_adapter_settings(core_runtime_settings)
    language_settings = component_settings_for(
        core_runtime_settings, component_name="language"
    )
    standard = language_settings.get("standard", {})
    standard_provider = (
        str(standard.get("provider", "")).strip() if isinstance(standard, dict) else ""
    )

    def _profile_provider(name: str) -> str:
        profile = language_settings.get(name, {})
        if not isinstance(profile, dict):
            return standard_provider
        provider = str(profile.get("provider", "")).strip()
        return provider if provider != "" else standard_provider

    providers = tuple(
        dict.fromkeys(
            [
                provider
                for provider in (
                    _profile_provider("quick"),
                    standard_provider,
                    _profile_provider("deep"),
                )
                if provider != ""
            ]
        )
    )
    if len(providers) == 0:
        providers = tuple(adapter_settings.providers.keys())
    return max_retry_budget_seconds(
        settings=adapter_settings,
        providers=providers,
        margin_seconds=_LMS_TIMEOUT_MARGIN_SECONDS,
    )


def _list_tool_system_hints(client: BrainClient) -> tuple[ToolSystemHint, ...]:
    """Return tool-system hints when the connected Core exposes them."""
    list_hints = getattr(client, "list_tool_system_hints", None)
    if not callable(list_hints):
        return ()
    try:
        return tuple(list_hints())
    except BrainSdkError as exc:
        _LOGGER.warning(
            "brain assistant tool-system hints unavailable",
            extra={"error_type": type(exc).__name__, "error_message": str(exc)},
        )
        return ()


def _create_runtime(
    *,
    client: BrainClient,
    settings: ActorSettings,
    core_settings: CoreSettings | None = None,
    language_request_timeout_seconds: float | None = None,
) -> _AgentRuntime:
    """Create one fully wired agent runtime from the published Core surface."""
    personality = str(getattr(settings.agent, "personality", "default"))
    operator_profile = str(
        getattr(settings.agent, "operator_profile", "Refer to me as 'boss'")
    )
    system_prompt_append = str(getattr(settings.agent, "system_prompt_append", ""))
    session_start_mode = getattr(settings.agent, "session_start_mode", "existing")
    if session_start_mode == "new":
        session = client.memory_create_session()
    else:
        try:
            session = client.memory_get_latest_or_create_session()
        except Exception:
            session = client.memory_create_session()
    ops = client.describe_ops()
    always_on_ops = client.list_always_on_ops()
    tool_system_hints = render_system_tool_hints(_list_tool_system_hints(client))
    system_blocks = render_system_prompt_blocks(
        personality,
        operator_profile=operator_profile,
        system_tool_hints=tool_system_hints,
        system_prompt_append=system_prompt_append,
    )
    denied_op_ids = frozenset(
        item.strip()
        for item in settings.agent.op_discovery_deny_list
        if item.strip() != ""
    )
    turn_state = _TurnState(
        always_on_op_ids=frozenset(
            item.op_id for item in always_on_ops if item.op_id not in denied_op_ids
        ),
        denied_op_ids=denied_op_ids,
        strip_keys=frozenset(_AGENT_CONTEXT_PROPERTIES),
    )
    turn_state.reset_active_tools()

    model = AgentToolModel(
        client=client,
        turn_state=turn_state,
        timeout_seconds=language_request_timeout_seconds,
        session_id=session.session_id,
        source=str(settings.agent.source),
        principal=str(settings.agent.principal),
        system_blocks=system_blocks,
        tool_approvals={
            **{item.op_id: item.approval for item in ops},
            _SEARCH_TOOLS_TOOL_NAME: "never",
            _GET_TOOL_INFO_TOOL_NAME: "never",
        },
        extra_input_properties=_AGENT_CONTEXT_PROPERTIES,
        discovery_tool_names=_DISCOVERY_TOOL_NAMES,
        operator_recovery_notifier=_notify_operator_of_language_recovery,
        recovery_notice_message=_LMS_RECOVERY_IN_PROGRESS_RESPONSE,
        operator_intermediate_text_notifier=(
            _notify_operator_of_intermediate_text
            if getattr(settings.agent, "surface_intermediate_text", False)
            else None
        ),
    )
    toolset = filtered_brain_toolset(
        client=client,
        descriptors=ops,
        turn_state=turn_state,
        invocation_context=turn_state,
        extra_input_properties=_AGENT_CONTEXT_PROPERTIES,
        include_discovery_tools=True,
    )
    from lib.agent.history import build_history_processor

    history_processor = build_history_processor(
        client=client,
        timeout_seconds=language_request_timeout_seconds,
        compress_threshold=settings.agent.tool_return_compress_threshold,
        max_chars=settings.agent.tool_return_max_chars,
        tier2_hop_threshold=settings.agent.tool_loop_tier2_hop_threshold,
        compress_system_prompt=_COMPRESS_SYSTEM_PROMPT,
        compress_user_template=_COMPRESS_USER_PROMPT_TEMPLATE,
        discovery_tool_names=_DISCOVERY_TOOL_NAMES,
    )
    agent = Agent(
        model,
        system_prompt="",
        retries=_AGENT_TOOL_CALL_RETRIES,
        max_concurrency=_AGENT_MAX_CONCURRENCY,
        toolsets=[toolset],
        history_processors=[history_processor],
        instrument=None,
    )
    return _AgentRuntime(
        client=client,
        session_id=session.session_id,
        turn_state=turn_state,
        model=model,
        agent=agent,
        language_request_timeout_seconds=(
            0.0
            if language_request_timeout_seconds is None
            else language_request_timeout_seconds
        ),
        preferred_timezone=str(
            getattr(
                getattr(core_settings, "profile", None), "preferred_timezone", "UTC"
            )
        ),
        system_blocks=system_blocks,
        environment_context_entries=tuple(
            getattr(settings.agent, "environment_context", ())
        ),
    )


def _long_poll_timeout_seconds(*, sdk_timeout_seconds: float) -> float:
    """Choose one bounded long-poll timeout that stays under the HTTP timeout."""
    return max(_MIN_LONG_POLL_SECONDS, sdk_timeout_seconds - _LONG_POLL_BUFFER_SECONDS)


def _format_user_prompt(
    *,
    instruction: RelayOperatorInstruction,
    context: MemoryContextBlock,
    environment_context: InferenceEnvironmentContext | None = None,
) -> list[UserContent]:
    """Build one structured user-context payload before the current instruction."""
    parts: list[UserContent] = [
        FocusContentPart(
            text="" if context.current_focus is None else context.current_focus
        ),
        ConversationSummaryContentPart(text=context.recent_conversation_summary),
        CachePoint(),
    ]
    if environment_context is not None and len(environment_context.items) > 0:
        parts.append(EnvironmentContextContentPart(items=environment_context.items))
    parts.extend(
        DialogueTurnContentPart(
            role=turn.role,
            text=turn.content,
            is_summary=turn.is_summary,
        )
        for turn in context.recent_turns
    )
    parts.extend(
        ReferenceSnippetContentPart(text=snippet)
        for snippet in context.reference_snippets
    )
    parts.append(
        OperatorMessageContentPart(
            channel=instruction.source,
            sender_e164=instruction.sender_e164,
            message_text=instruction.message_text,
            approval_intent=instruction.approval_intent,
            reaction_emoji=instruction.reaction_emoji,
            quote_target_timestamp_ms=instruction.quote_target_timestamp_ms,
            reaction_target_timestamp_ms=instruction.reaction_target_timestamp_ms,
            reply_to_proposal_token=instruction.reply_to_proposal_token,
            reaction_to_proposal_token=instruction.reaction_to_proposal_token,
        )
    )
    return parts


def _instruction_context_message(instruction: RelayOperatorInstruction) -> str:
    """Return the best available text surrogate for one inbound operator instruction."""
    message_text = instruction.message_text
    if message_text != "":
        return message_text
    if instruction.approval_intent is not None:
        if instruction.reaction_emoji is not None and instruction.reaction_emoji != "":
            return f"[signal reaction approval:{instruction.approval_intent} emoji:{instruction.reaction_emoji}]"
        return f"[signal approval:{instruction.approval_intent}]"
    if instruction.reaction_emoji is not None and instruction.reaction_emoji != "":
        return f"[signal reaction emoji:{instruction.reaction_emoji}]"
    return "[signal message]"


async def _notify_operator_of_language_recovery(
    *,
    client: BrainClient,
    turn_state: _TurnState,
    session_id: str,
    message: str,
    reasoning_level: str,
) -> None:
    """Send one best-effort operator-facing notice that Language recovery is underway."""
    payload: dict[str, object] = {
        "actor": "operator",
        "channel": turn_state.channel,
        "message": message,
        "conversational_memory": {
            "session_id": session_id,
            "model": "brain-sdk-lms",
            "provider": "brain-sdk",
            "token_count": estimate_token_count(message),
            "reasoning_level": reasoning_level,
        },
    }
    try:
        await asyncio.to_thread(
            call_with_optional_meta,
            client.invoke_op,
            meta=turn_state.nested_call_meta(),
            op_id=_RELAY_NOTIFY_OP_ID,
            input_payload=payload,
            actor="operator",
            channel=turn_state.channel,
        )
    except (BrainTransportError, BrainDomainError) as exc:
        _LOGGER.warning(
            "brain assistant lms recovery notify failed: %s",
            exc,
            extra={
                "op_id": _RELAY_NOTIFY_OP_ID,
                "channel": turn_state.channel,
                "actor": "operator",
            },
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "brain assistant lms recovery notify failed",
            extra={
                "op_id": _RELAY_NOTIFY_OP_ID,
                "channel": turn_state.channel,
                "actor": "operator",
            },
        )


async def _notify_operator_of_intermediate_text(
    *,
    client: BrainClient,
    turn_state: _TurnState,
    session_id: str,
    text: str,
    reasoning_level: str,
) -> None:
    """Send one best-effort operator-facing notice carrying interim model commentary.

    Surfaces text the model emitted alongside a tool call so the operator
    sees chain-of-thought as the turn unfolds. Wraps the model text in
    ``_INTERMEDIATE_TEXT_FORMAT`` so the operator can distinguish interim
    commentary from final replies.
    """
    formatted = _INTERMEDIATE_TEXT_FORMAT.format(text=text)
    payload: dict[str, object] = {
        "actor": "operator",
        "channel": turn_state.channel,
        "message": formatted,
        "conversational_memory": {
            "session_id": session_id,
            "model": "brain-sdk-lms",
            "provider": "brain-sdk",
            "token_count": estimate_token_count(formatted),
            "reasoning_level": reasoning_level,
        },
    }
    try:
        await asyncio.to_thread(
            call_with_optional_meta,
            client.invoke_op,
            meta=turn_state.nested_call_meta(),
            op_id=_RELAY_NOTIFY_OP_ID,
            input_payload=payload,
            actor="operator",
            channel=turn_state.channel,
        )
    except (BrainTransportError, BrainDomainError) as exc:
        _LOGGER.warning(
            "brain assistant intermediate text notify failed: %s",
            exc,
            extra={
                "op_id": _RELAY_NOTIFY_OP_ID,
                "channel": turn_state.channel,
                "actor": "operator",
            },
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "brain assistant intermediate text notify failed",
            extra={
                "op_id": _RELAY_NOTIFY_OP_ID,
                "channel": turn_state.channel,
                "actor": "operator",
            },
        )


def _is_language_operation(operation: str) -> bool:
    """Return True when one SDK operation is an Language generation call."""
    return operation in {"lms.chat", "lms.chat_with_tools"}


def _classify_language_failure_response(exc: BrainSdkError) -> str | None:
    """Return one fallback operator response for handled Language failures."""
    operation = getattr(exc, "operation", "")
    if not isinstance(operation, str) or not _is_language_operation(operation):
        return None
    if isinstance(exc, BrainDependencyError):
        if is_retryable_language_throttle(exc):
            return _LMS_THROTTLE_RESPONSE
        if is_retryable_language_timeout(exc):
            return _LMS_TIMEOUT_RESPONSE
        return _LMS_GENERIC_ERROR_RESPONSE
    if isinstance(exc, BrainTransportError):
        if is_retryable_language_transport_timeout(exc):
            return _LMS_TIMEOUT_RESPONSE
        return _LMS_GENERIC_ERROR_RESPONSE
    if isinstance(exc, BrainDomainError):
        return _LMS_GENERIC_ERROR_RESPONSE
    return None


async def _process_instruction(
    *,
    runtime: _AgentRuntime,
    instruction: RelayOperatorInstruction,
) -> str:
    """Handle one inbound operator instruction end-to-end."""
    runtime.turn_state.prune_pending_invocations()
    runtime.turn_state.begin_turn_trace()
    with _AgentTurnObservation(runtime=runtime, instruction=instruction) as turn_span:
        set_current_span_attributes(
            {
                "brain.operation": "assistant.turn",
                "brain.trace_id": runtime.turn_state.trace_id,
                "brain.envelope_id": runtime.turn_state.root_envelope_id,
                "brain.session_id": runtime.session_id,
                "brain.principal": runtime.turn_state.actor,
                "brain.source": instruction.source,
            }
        )
        assemble_context = getattr(runtime.client, "memory_assemble_context", None)
        if callable(assemble_context):
            turn_context = await asyncio.to_thread(
                call_with_optional_meta,
                assemble_context,
                meta=runtime.turn_state.nested_call_meta(),
                session_id=runtime.session_id,
                message=_instruction_context_message(instruction),
                instruction=instruction,
            )
        else:
            _inbound_turn = await asyncio.to_thread(
                call_with_optional_meta,
                runtime.client.memory_record_inbound_turn,
                meta=runtime.turn_state.nested_call_meta(),
                session_id=runtime.session_id,
                message=_instruction_context_message(instruction),
                instruction=instruction,
            )
            context = await asyncio.to_thread(
                call_with_optional_meta,
                runtime.client.memory_assemble_snapshot,
                meta=runtime.turn_state.nested_call_meta(),
                session_id=runtime.session_id,
            )
            turn_context = type(
                "_TurnContext",
                (),
                {
                    "session_id": runtime.session_id,
                    "inbound_turn": _inbound_turn,
                    "context": context,
                },
            )()
        runtime.session_id = turn_context.session_id
        runtime.model._session_id = turn_context.session_id
        _inbound_turn = turn_context.inbound_turn
        runtime.turn_state.conversation_episode_id = getattr(
            _inbound_turn, "conversation_episode_id", ""
        )
        _update_agent_turn_observation_session(span=turn_span, runtime=runtime)
        context = turn_context.context
        runtime.turn_state.actor = "operator"
        runtime.turn_state.channel = instruction.source
        runtime.turn_state.message_text = instruction.message_text
        runtime.turn_state.reply_to_proposal_token = (
            ""
            if instruction.reply_to_proposal_token is None
            else instruction.reply_to_proposal_token
        )
        runtime.turn_state.reaction_to_proposal_token = (
            ""
            if instruction.reaction_to_proposal_token is None
            else instruction.reaction_to_proposal_token
        )
        environment_context, environment_diagnostics = await asyncio.to_thread(
            assemble_environment_context,
            client=runtime.client,
            entries=runtime.environment_context_entries,
            actor=runtime.turn_state.actor,
            channel=runtime.turn_state.channel,
            preferred_timezone=runtime.preferred_timezone,
            meta=runtime.turn_state.nested_call_meta(),
        )
        for diagnostic in environment_diagnostics:
            _LOGGER.error(
                "brain assistant environment context op failed",
                extra={
                    "op_id": diagnostic.op_id,
                    "error_type": diagnostic.error_type,
                    "error_message": diagnostic.message,
                },
            )
        runtime.turn_state.reset_active_tools()
        runtime.model.last_result = None
        try:
            result = await runtime.agent.run(
                _format_user_prompt(
                    instruction=instruction,
                    context=context,
                    environment_context=environment_context,
                )
            )
            response_text = str(result.output).strip()
            if response_text == "":
                response_text = "I do not have a response yet."
        except BrainSdkError as exc:
            fallback_response = _classify_language_failure_response(exc)
            if fallback_response is None:
                raise
            _LOGGER.warning(
                "brain assistant lms request failed; returning fallback response",
                extra={
                    "operation": getattr(exc, "operation", ""),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "fallback_kind": (
                        "throttle"
                        if fallback_response == _LMS_THROTTLE_RESPONSE
                        else "timeout"
                        if fallback_response == _LMS_TIMEOUT_RESPONSE
                        else "generic"
                    ),
                },
            )
            response_text = fallback_response
        chat = runtime.model.last_result
        await _route_outbound_response(
            runtime=runtime,
            instruction=instruction,
            response_text=response_text,
            model="brain-sdk-lms" if chat is None else chat.model,
            provider="brain-sdk" if chat is None else chat.provider,
            reasoning_level=runtime.model.last_used_profile_name,
        )
        _complete_agent_turn_observation(
            span=turn_span,
            response_text=response_text,
        )
        return response_text


async def _route_outbound_response(
    *,
    runtime: _AgentRuntime,
    instruction: RelayOperatorInstruction,
    response_text: str,
    model: str,
    provider: str,
    reasoning_level: str,
) -> bool:
    """Deliver one finalized response via Relay outbound notify op."""
    payload: dict[str, object] = {
        "actor": "operator",
        "channel": instruction.source,
        "message": response_text,
        "conversational_memory": {
            "session_id": runtime.session_id,
            "model": model,
            "provider": provider,
            "token_count": estimate_token_count(response_text),
            "reasoning_level": reasoning_level,
        },
    }
    try:
        await asyncio.to_thread(
            call_with_optional_meta,
            runtime.client.invoke_op,
            meta=runtime.turn_state.nested_call_meta(),
            op_id=_RELAY_NOTIFY_OP_ID,
            input_payload=payload,
            actor="operator",
            channel=instruction.source,
        )
        return True
    except (BrainTransportError, BrainDomainError) as exc:
        _LOGGER.warning(
            "brain assistant outbound notify failed: %s",
            exc,
            extra={
                "op_id": _RELAY_NOTIFY_OP_ID,
                "channel": instruction.source,
                "actor": "operator",
            },
        )
        return False
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "brain assistant outbound notify failed",
            extra={
                "op_id": _RELAY_NOTIFY_OP_ID,
                "channel": instruction.source,
                "actor": "operator",
            },
        )
        return False


async def _run_main() -> None:
    """Run the long-lived Brain Assistant process inside one event loop."""
    global _RUNNING
    _RUNNING = True

    settings, core_runtime_settings = _load_startup_settings()
    core_settings = core_runtime_settings.core
    _configure_logging(settings=settings)
    bootstrap_observability(
        settings=settings.observability,
        service_name=str(settings.logging.process_name),
        environment=str(settings.logging.environment),
    )
    heartbeat_path = _resolve_heartbeat_path()
    _write_heartbeat(path=heartbeat_path)

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    client = BrainClient(config=_sdk_config_from_settings(settings))
    try:
        runtime = _create_runtime(
            client=client,
            settings=settings,
            core_settings=core_settings,
            language_request_timeout_seconds=_derive_language_request_timeout_seconds(
                core_runtime_settings
            ),
        )
        _LOGGER.info(
            "brain assistant started",
            extra={
                "core_host": settings.core.host,
                "core_port": settings.core.port,
                "timeout_seconds": settings.core.timeout_seconds,
                "language_request_timeout_seconds": runtime.language_request_timeout_seconds,
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
                _write_heartbeat(path=heartbeat_path)
                instruction = await asyncio.to_thread(
                    runtime.client.relay_poll_operator_instruction,
                    wait_timeout_seconds=wait_timeout_seconds,
                )
                _write_heartbeat(path=heartbeat_path)
                if instruction is None:
                    continue
                _LOGGER.debug(
                    "brain assistant received instruction",
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
                    "brain assistant completed turn",
                    extra={
                        "channel": instruction.source,
                        "sender_e164": instruction.sender_e164,
                        "response": response_text,
                    },
                )
                _write_heartbeat(path=heartbeat_path)
            except (BrainTransportError, BrainDomainError) as exc:
                # Expected during Brain Core restarts and transient network
                # blips. Log a single-line warning, retry on the next tick.
                _LOGGER.warning("brain assistant poll failed (will retry): %s", exc)
                _write_heartbeat(path=heartbeat_path)
                await asyncio.sleep(_TURN_FAILURE_BACKOFF_SECONDS)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("brain assistant turn failed")
                _write_heartbeat(path=heartbeat_path)
                await asyncio.sleep(_TURN_FAILURE_BACKOFF_SECONDS)
    finally:
        client.close()
        _LOGGER.info("brain assistant stopped")


def main() -> None:
    """Run the long-lived Brain Assistant process."""
    asyncio.run(_run_main())


if __name__ == "__main__":
    main()
