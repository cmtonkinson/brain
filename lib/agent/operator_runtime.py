"""Operator-facing agent runtime shared by process entrypoints.

This module owns the conversational Assistant turn machinery that is not
process lifecycle: runtime assembly, Recall context handoff, operator prompt
content construction, Relay outbound delivery, and turn observability.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic_ai import Agent
from pydantic_ai.messages import CachePoint, UserContent

import lib.agent.history as history
from lib.agent.history import estimate_token_count
from lib.agent.recovery import (
    is_retryable_language_throttle,
    is_retryable_language_timeout,
    is_retryable_language_transport_timeout,
)
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
    is_observability_enabled,
    set_current_span_attributes,
    set_span_attributes,
)
from resources.adapters.llm.config import (
    max_retry_budget_seconds,
    resolve_llm_adapter_settings,
)

_LOGGER = logging.getLogger(__name__)

LMS_THROTTLE_RESPONSE = (
    "I'm temporarily rate limited by the language model provider. "
    "Please try again in a minute."
)
LMS_TIMEOUT_RESPONSE = (
    "I'm temporarily having trouble reaching the language model provider. "
    "Please try again in a minute."
)
LMS_GENERIC_ERROR_RESPONSE = (
    "I hit an internal language-model error while working on that. Please try again."
)
LMS_RECOVERY_IN_PROGRESS_RESPONSE = (
    "I'm sorry, but the language model provider is having trouble. "
    "I'm still working on it and will keep trying."
)
INTERMEDIATE_TEXT_FORMAT = "_... {text}..._"
LMS_TIMEOUT_MARGIN_SECONDS = 2.0
AGENT_TOOL_CALL_RETRIES = 3
AGENT_MAX_CONCURRENCY = 1
RELAY_NOTIFY_OP_ID = "relay-notify"
DISCOVERY_TOOL_NAMES = frozenset({SEARCH_TOOLS_TOOL_NAME, GET_TOOL_INFO_TOOL_NAME})

_MODULE_DIR = Path(__file__).resolve().parent
COMPRESS_SYSTEM_PROMPT_PATH = _MODULE_DIR / "prompts" / "compress-tool-return.txt"
COMPRESS_USER_PROMPT_TEMPLATE_PATH = (
    _MODULE_DIR / "prompts" / "compress-tool-return-user-template.txt"
)
AGENT_CONTEXT_PROPERTIES_PATH = _MODULE_DIR / "tool-context-properties.json"

TurnState = DefaultTurnState
OperatorPendingInvocation = PendingInvocation


@dataclass(slots=True)
class OperatorAgentRuntime:
    """Assembled operator-facing agent runtime dependencies."""

    client: BrainClient
    session_id: str
    turn_state: TurnState
    model: AgentToolModel
    agent: Agent[None, str]
    language_request_timeout_seconds: float
    preferred_timezone: str = "UTC"
    system_blocks: tuple[InferenceSystemBlock, ...] = ()
    environment_context_entries: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class _TurnContext:
    """Recall context bundle required to run one operator turn."""

    session_id: str
    inbound_turn: Any
    context: MemoryContextBlock


def load_prompt_file(path: Path) -> str:
    """Load one prompt text file from disk without altering its contents."""
    return path.read_text(encoding="utf-8")


def load_agent_context_properties(
    *, path: Path = AGENT_CONTEXT_PROPERTIES_PATH
) -> dict[str, object]:
    """Load agent-only tool schema properties from the shared JSON file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


AGENT_CONTEXT_PROPERTIES = load_agent_context_properties()
COMPRESS_SYSTEM_PROMPT = load_prompt_file(COMPRESS_SYSTEM_PROMPT_PATH)
COMPRESS_USER_PROMPT_TEMPLATE = load_prompt_file(COMPRESS_USER_PROMPT_TEMPLATE_PATH)


def sdk_config_from_settings(settings: ActorSettings) -> BrainSdkConfig:
    """Project actor settings into the SDK client configuration model."""
    return BrainSdkConfig(
        host=str(settings.core.host),
        port=int(settings.core.port),
        timeout_seconds=float(settings.core.timeout_seconds),
        source=str(settings.agent.source),
        principal=str(settings.agent.principal),
    )


def derive_language_request_timeout_seconds(
    core_runtime_settings: CoreRuntimeSettings,
) -> float:
    """Return one derived agent-to-Core timeout for Language requests."""
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
            provider
            for provider in (
                _profile_provider("quick"),
                standard_provider,
                _profile_provider("deep"),
            )
            if provider != ""
        )
    )
    if len(providers) == 0:
        providers = tuple(adapter_settings.providers.keys())
    return max_retry_budget_seconds(
        settings=adapter_settings,
        providers=providers,
        margin_seconds=LMS_TIMEOUT_MARGIN_SECONDS,
    )


def list_tool_system_hints(client: BrainClient) -> tuple[ToolSystemHint, ...]:
    """Return tool-system hints when the connected Core exposes them."""
    list_hints = getattr(client, "list_tool_system_hints", None)
    if not callable(list_hints):
        return ()
    try:
        return tuple(cast(Any, list_hints)())
    except BrainSdkError as exc:
        _LOGGER.warning(
            "brain assistant tool-system hints unavailable",
            extra={"error_type": type(exc).__name__, "error_message": str(exc)},
        )
        return ()


def create_runtime(
    *,
    client: BrainClient,
    settings: ActorSettings,
    core_settings: CoreSettings | None = None,
    language_request_timeout_seconds: float | None = None,
) -> OperatorAgentRuntime:
    """Create one fully wired operator-facing runtime from the Core SDK."""
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
    tool_system_hints = render_system_tool_hints(list_tool_system_hints(client))
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
    turn_state = TurnState(
        always_on_op_ids=frozenset(
            item.op_id for item in always_on_ops if item.op_id not in denied_op_ids
        ),
        denied_op_ids=denied_op_ids,
        strip_keys=frozenset(AGENT_CONTEXT_PROPERTIES),
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
            SEARCH_TOOLS_TOOL_NAME: "never",
            GET_TOOL_INFO_TOOL_NAME: "never",
        },
        extra_input_properties=AGENT_CONTEXT_PROPERTIES,
        discovery_tool_names=DISCOVERY_TOOL_NAMES,
        operator_recovery_notifier=notify_operator_of_language_recovery,
        recovery_notice_message=LMS_RECOVERY_IN_PROGRESS_RESPONSE,
        operator_intermediate_text_notifier=(
            notify_operator_of_intermediate_text
            if getattr(settings.agent, "surface_intermediate_text", False)
            else None
        ),
    )
    toolset = filtered_brain_toolset(
        client=client,
        descriptors=ops,
        turn_state=turn_state,
        invocation_context=turn_state,
        extra_input_properties=AGENT_CONTEXT_PROPERTIES,
        include_discovery_tools=True,
    )
    history_processor = history.build_history_processor(
        client=client,
        timeout_seconds=language_request_timeout_seconds,
        compress_threshold=settings.agent.tool_return_compress_threshold,
        max_chars=settings.agent.tool_return_max_chars,
        tier2_hop_threshold=settings.agent.tool_loop_tier2_hop_threshold,
        compress_system_prompt=COMPRESS_SYSTEM_PROMPT,
        compress_user_template=COMPRESS_USER_PROMPT_TEMPLATE,
        discovery_tool_names=DISCOVERY_TOOL_NAMES,
    )
    agent = Agent(
        model,
        system_prompt="",
        retries=AGENT_TOOL_CALL_RETRIES,
        max_concurrency=AGENT_MAX_CONCURRENCY,
        toolsets=[toolset],
        history_processors=[history_processor],
        instrument=None,
    )
    return OperatorAgentRuntime(
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


def format_user_prompt(
    *,
    instruction: RelayOperatorInstruction,
    context: MemoryContextBlock,
    environment_context: InferenceEnvironmentContext | None = None,
) -> list[UserContent]:
    """Build one structured user-context payload before the current instruction."""
    parts: list[Any] = [
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
    return cast(list[UserContent], parts)


def instruction_context_message(instruction: RelayOperatorInstruction) -> str:
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


async def notify_operator_of_language_recovery(
    *,
    client: BrainClient,
    turn_state: TurnState,
    session_id: str,
    message: str,
    reasoning_level: str,
) -> None:
    """Send one best-effort operator-facing Language recovery notice."""
    await _notify_operator(
        client=client,
        turn_state=turn_state,
        session_id=session_id,
        message=message,
        reasoning_level=reasoning_level,
        log_label="lms recovery",
    )


async def notify_operator_of_intermediate_text(
    *,
    client: BrainClient,
    turn_state: TurnState,
    session_id: str,
    text: str,
    reasoning_level: str,
) -> None:
    """Send one best-effort operator-facing interim model commentary notice."""
    await _notify_operator(
        client=client,
        turn_state=turn_state,
        session_id=session_id,
        message=INTERMEDIATE_TEXT_FORMAT.format(text=text),
        reasoning_level=reasoning_level,
        log_label="intermediate text",
    )


async def _notify_operator(
    *,
    client: BrainClient,
    turn_state: TurnState,
    session_id: str,
    message: str,
    reasoning_level: str,
    log_label: str,
) -> None:
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
            op_id=RELAY_NOTIFY_OP_ID,
            input_payload=payload,
            actor="operator",
            channel=turn_state.channel,
        )
    except (BrainTransportError, BrainDomainError) as exc:
        _LOGGER.warning(
            "brain assistant %s notify failed: %s",
            log_label,
            exc,
            extra={
                "op_id": RELAY_NOTIFY_OP_ID,
                "channel": turn_state.channel,
                "actor": "operator",
            },
        )
    except Exception:
        _LOGGER.exception(
            "brain assistant %s notify failed",
            log_label,
            extra={
                "op_id": RELAY_NOTIFY_OP_ID,
                "channel": turn_state.channel,
                "actor": "operator",
            },
        )


def classify_language_failure_response(exc: BrainSdkError) -> str | None:
    """Return one fallback operator response for handled Language failures."""
    operation = getattr(exc, "operation", "")
    if not isinstance(operation, str) or operation not in {
        "lms.chat",
        "lms.chat_with_tools",
    }:
        return None
    if isinstance(exc, BrainDependencyError):
        if is_retryable_language_throttle(exc):
            return LMS_THROTTLE_RESPONSE
        if is_retryable_language_timeout(exc):
            return LMS_TIMEOUT_RESPONSE
        return LMS_GENERIC_ERROR_RESPONSE
    if isinstance(exc, BrainTransportError):
        if is_retryable_language_transport_timeout(exc):
            return LMS_TIMEOUT_RESPONSE
        return LMS_GENERIC_ERROR_RESPONSE
    if isinstance(exc, BrainDomainError):
        return LMS_GENERIC_ERROR_RESPONSE
    return None


async def process_instruction(
    *,
    runtime: OperatorAgentRuntime,
    instruction: RelayOperatorInstruction,
) -> str:
    """Handle one inbound operator instruction end-to-end."""
    runtime.turn_state.prune_pending_invocations()
    runtime.turn_state.begin_turn_trace()
    with AgentTurnObservation(runtime=runtime, instruction=instruction) as turn_span:
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
        turn_context = await _assemble_recall_context(
            runtime=runtime, instruction=instruction
        )
        runtime.session_id = turn_context.session_id
        runtime.model._session_id = turn_context.session_id
        inbound_turn = turn_context.inbound_turn
        runtime.turn_state.conversation_episode_id = getattr(
            inbound_turn, "conversation_episode_id", ""
        )
        update_agent_turn_observation_session(span=turn_span, runtime=runtime)
        context = turn_context.context
        runtime.turn_state.actor = "operator"
        runtime.turn_state.channel = instruction.source
        runtime.turn_state.message_text = instruction.message_text
        runtime.turn_state.reply_to_proposal_token = (
            instruction.reply_to_proposal_token or ""
        )
        runtime.turn_state.reaction_to_proposal_token = (
            instruction.reaction_to_proposal_token or ""
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
                format_user_prompt(
                    instruction=instruction,
                    context=context,
                    environment_context=environment_context,
                )
            )
            response_text = (
                str(result.output).strip() or "I do not have a response yet."
            )
        except BrainSdkError as exc:
            fallback_response = classify_language_failure_response(exc)
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
                        if fallback_response == LMS_THROTTLE_RESPONSE
                        else "timeout"
                        if fallback_response == LMS_TIMEOUT_RESPONSE
                        else "generic"
                    ),
                },
            )
            response_text = fallback_response
        chat = runtime.model.last_result
        await route_outbound_response(
            runtime=runtime,
            instruction=instruction,
            response_text=response_text,
            model="brain-sdk-lms" if chat is None else chat.model,
            provider="brain-sdk" if chat is None else chat.provider,
            reasoning_level=runtime.model.last_used_profile_name,
        )
        complete_agent_turn_observation(span=turn_span, response_text=response_text)
        return response_text
    raise RuntimeError("operator agent turn exited without a response")


async def _assemble_recall_context(
    *, runtime: OperatorAgentRuntime, instruction: RelayOperatorInstruction
) -> _TurnContext:
    assemble_context = getattr(runtime.client, "memory_assemble_context", None)
    if callable(assemble_context):
        return cast(
            _TurnContext,
            await asyncio.to_thread(
                call_with_optional_meta,
                assemble_context,
                meta=runtime.turn_state.nested_call_meta(),
                session_id=runtime.session_id,
                message=instruction_context_message(instruction),
                instruction=instruction,
            ),
        )
    inbound_turn = await asyncio.to_thread(
        call_with_optional_meta,
        runtime.client.memory_record_inbound_turn,
        meta=runtime.turn_state.nested_call_meta(),
        session_id=runtime.session_id,
        message=instruction_context_message(instruction),
        instruction=instruction,
    )
    context = await asyncio.to_thread(
        call_with_optional_meta,
        runtime.client.memory_assemble_snapshot,
        meta=runtime.turn_state.nested_call_meta(),
        session_id=runtime.session_id,
    )
    return _TurnContext(
        session_id=runtime.session_id,
        inbound_turn=inbound_turn,
        context=context,
    )


async def route_outbound_response(
    *,
    runtime: OperatorAgentRuntime,
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
            op_id=RELAY_NOTIFY_OP_ID,
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
                "op_id": RELAY_NOTIFY_OP_ID,
                "channel": instruction.source,
                "actor": "operator",
            },
        )
        return False
    except Exception:
        _LOGGER.exception(
            "brain assistant outbound notify failed",
            extra={
                "op_id": RELAY_NOTIFY_OP_ID,
                "channel": instruction.source,
                "actor": "operator",
            },
        )
        return False


def json_dumps_or_empty(value: object | None) -> str:
    """Serialize one value for Langfuse JSON-string observation fields."""
    if value is None:
        return ""
    return json.dumps(value, sort_keys=True, default=str)


def operator_observation_input(
    *,
    system_blocks: tuple[InferenceSystemBlock, ...],
    instruction: RelayOperatorInstruction,
) -> dict[str, object]:
    """Return the Langfuse-facing root turn input payload."""
    payload: dict[str, object] = {
        "message": instruction_context_message(instruction),
        "channel": instruction.source,
        "system_prompt": system_blocks_for_observation(system_blocks),
    }
    if instruction.sender_e164 != "":
        payload["sender_e164"] = instruction.sender_e164
    if instruction.approval_intent is not None:
        payload["approval_intent"] = instruction.approval_intent
    if instruction.reaction_emoji is not None:
        payload["reaction_emoji"] = instruction.reaction_emoji
    return payload


def system_blocks_for_observation(blocks: tuple[InferenceSystemBlock, ...]) -> str:
    """Render canonical system blocks into one stable observation string."""
    return "\n\n".join(
        f"<{block.kind}>\n{block.text}\n</{block.kind}>"
        for block in blocks
        if block.text != ""
    )


class AgentTurnObservation:
    """Context manager for one Langfuse-compatible Agent turn span."""

    def __init__(
        self,
        *,
        runtime: OperatorAgentRuntime,
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
        observation_input = operator_observation_input(
            system_blocks=self._runtime.system_blocks,
            instruction=self._instruction,
        )
        input_json = json_dumps_or_empty(observation_input)
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

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
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


def update_agent_turn_observation_session(
    *, span: object | None, runtime: OperatorAgentRuntime
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


def complete_agent_turn_observation(*, span: object | None, response_text: str) -> None:
    """Attach the final Agent response to the root turn span."""
    if span is None:
        return
    output_json = json_dumps_or_empty({"response": response_text})
    set_span_attributes(
        span,
        {
            "langfuse.observation.output": output_json,
            "langfuse.trace.output": output_json,
            "langfuse.observation.metadata.outcome": "success",
        },
    )


__all__ = [
    "AGENT_CONTEXT_PROPERTIES",
    "AGENT_CONTEXT_PROPERTIES_PATH",
    "COMPRESS_SYSTEM_PROMPT",
    "COMPRESS_SYSTEM_PROMPT_PATH",
    "COMPRESS_USER_PROMPT_TEMPLATE",
    "COMPRESS_USER_PROMPT_TEMPLATE_PATH",
    "DISCOVERY_TOOL_NAMES",
    "GET_TOOL_INFO_TOOL_NAME",
    "LMS_GENERIC_ERROR_RESPONSE",
    "LMS_RECOVERY_IN_PROGRESS_RESPONSE",
    "LMS_THROTTLE_RESPONSE",
    "LMS_TIMEOUT_RESPONSE",
    "MAX_PENDING_INVOCATIONS",
    "OperatorAgentRuntime",
    "OperatorPendingInvocation",
    "SEARCH_TOOLS_TOOL_NAME",
    "TurnState",
    "AgentTurnObservation",
    "classify_language_failure_response",
    "complete_agent_turn_observation",
    "create_runtime",
    "derive_language_request_timeout_seconds",
    "format_user_prompt",
    "instruction_context_message",
    "json_dumps_or_empty",
    "list_tool_system_hints",
    "load_agent_context_properties",
    "load_prompt_file",
    "notify_operator_of_intermediate_text",
    "notify_operator_of_language_recovery",
    "operator_observation_input",
    "process_instruction",
    "route_outbound_response",
    "sdk_config_from_settings",
    "system_blocks_for_observation",
    "update_agent_turn_observation_session",
]
