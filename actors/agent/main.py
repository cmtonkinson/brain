"""Runtime entrypoint for the long-lived Brain Agent container."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import signal
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.messages import (
    CachePoint,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserContent,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.tools import ToolDefinition

from lib.sdk import (
    BrainClient,
    BrainConflictError,
    BrainDependencyError,
    BrainDomainError,
    BrainInternalError,
    BrainNotFoundError,
    BrainPolicyError,
    BrainSdkConfig,
    BrainTransportError,
    BrainValidationError,
    CapabilityDescriptor,
    LmsChatToolCall,
    LmsToolChatResult,
    MemoryContextBlock,
    MetaOverrides,
    SdkErrorDetail,
    SwitchboardOperatorInstruction,
    ToolSystemHint,
    render_system_prompt_blocks,
    render_system_tool_hints,
)
from lib.sdk.errors import BrainSdkError
from lib.shared.config import (
    ActorSettings,
    CoreRuntimeSettings,
    CoreSettings,
    load_actor_settings,
    load_core_runtime_settings,
)
from lib.shared.ids import generate_ulid_str
from lib.shared.language_model import (
    CachePointContentPart,
    ChatContentPart,
    ConversationSummaryContentPart,
    DialogueTurnContentPart,
    EnvironmentContextContentPart,
    FocusContentPart,
    InferenceAssistantTextEvent,
    InferenceCache,
    InferenceControls,
    InferenceCurrentTurn,
    InferenceEnvironmentContext,
    InferenceEnvironmentItem,
    InferenceMemoryContext,
    InferenceMemoryTurn,
    InferenceMeta,
    InferenceOperatorMessage,
    InferenceParallelToolCalls,
    InferenceReferenceSnippet,
    InferenceRequest,
    InferenceSystem,
    InferenceSystemBlock,
    InferenceToolCall,
    InferenceToolCallBatchEvent,
    InferenceToolChoice,
    InferenceToolDefinition,
    InferenceToolExecutionHints,
    InferenceToolResult,
    InferenceToolResultBatchEvent,
    InferenceToolResultPayload,
    OperatorMessageContentPart,
    ReferenceSnippetContentPart,
    TextContentPart,
)
from lib.sdk.environment import assemble_environment_context
from lib.shared.observability import (
    bootstrap_observability,
    is_observability_enabled,
)
from resources.adapters.llm.config import (
    max_timeout_retry_budget_seconds,
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
_LMS_TIMEOUT_MARGIN_SECONDS = 2.0
_LMS_PROVIDER_RETRY_DELAYS_SECONDS = (0.5, 1.0)
_LMS_RECOVERY_NOTICE_DELAY_THRESHOLD_SECONDS = 1.0
_AGENT_DIR = Path(__file__).resolve().parent
_PROMPTS_DIR = _AGENT_DIR / "prompts"
_COMPRESS_SYSTEM_PROMPT_PATH = _PROMPTS_DIR / "compress-tool-return.txt"
_COMPRESS_USER_PROMPT_TEMPLATE_PATH = (
    _PROMPTS_DIR / "compress-tool-return-user-template.txt"
)
_AGENT_CONTEXT_PROPERTIES_PATH = _AGENT_DIR / "tool-context-properties.json"
_SEARCH_TOOLS_TOOL_NAME = "search_tools"
_GET_TOOL_INFO_TOOL_NAME = "get_tool_info"
_MAX_PENDING_INVOCATIONS = 128
_HEARTBEAT_FILE_ENV = "BRAIN_AGENT_HEARTBEAT_FILE"
_HEARTBEAT_PATH = Path("/run/brain/agent-heartbeat")
_PROMPT_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
_INVALID_TOOL_CALL_RETRY_INSTRUCTION = (
    "A prior response attempted to call tool names that were not in the current "
    "advertised tool list. On this response, only emit tool calls whose exact "
    "names appear in the provided tool definitions for this hop. Tool ids or "
    "tool names mentioned inside discovery results are informational only until "
    "the runtime explicitly advertises them as callable tools on a later hop."
)
_DISCOVERY_TOOL_NAMES = frozenset({_SEARCH_TOOLS_TOOL_NAME, _GET_TOOL_INFO_TOOL_NAME})
_ROLLING_CACHE_BASE_CONTINUATION_PROBABILITY = 0.20
_ROLLING_CACHE_EXPLORE_WEIGHT = 0.35
_ROLLING_CACHE_DISCOVERY_WEIGHT = 0.25
_ROLLING_CACHE_FAILURE_WEIGHT = 0.20
_ROLLING_CACHE_NOT_FOUND_WEIGHT = 0.10
_ROLLING_CACHE_DECISIVE_SUCCESS_WEIGHT = -0.30
_ROLLING_CACHE_HOP_DECAY = -0.03
_ROLLING_CACHE_MIN_PROBABILITY = 0.05
_ROLLING_CACHE_MAX_PROBABILITY = 0.95
_ROLLING_CACHE_MAX_FUTURE_REUSES = 3
_INVALID_TOOL_CALL_REPAIR_ATTEMPTS = 3


def _set_current_span_attributes(attributes: dict[str, object | None]) -> None:
    """Attach attributes to the active OTel span when tracing is active."""
    try:
        from opentelemetry import trace
    except ImportError:
        return
    span = trace.get_current_span()
    if span is None:
        return
    for key, value in attributes.items():
        if value in (None, ""):
            continue
        span.set_attribute(key, value)


def _set_span_attributes(span: object, attributes: dict[str, object | None]) -> None:
    """Attach non-empty OTel-compatible attributes to one span."""
    set_attribute = getattr(span, "set_attribute", None)
    if not callable(set_attribute):
        return
    for key, value in attributes.items():
        if value in (None, "", {}, []):
            continue
        set_attribute(key, value)


def _json_dumps_or_empty(value: object | None) -> str:
    """Serialize one value for Langfuse JSON-string observation fields."""
    if value is None:
        return ""
    return json.dumps(value, sort_keys=True, default=str)


def _operator_observation_input(
    *,
    system_blocks: tuple[InferenceSystemBlock, ...],
    instruction: SwitchboardOperatorInstruction,
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


def _agent_turn_observation(
    *,
    runtime: "_AgentRuntime",
    instruction: SwitchboardOperatorInstruction,
):
    """Create one Langfuse-compatible root span for an Agent turn."""
    return _AgentTurnObservation(runtime=runtime, instruction=instruction)


class _AgentTurnObservation:
    """Context manager for one Langfuse-compatible Agent turn span."""

    def __init__(
        self,
        *,
        runtime: "_AgentRuntime",
        instruction: SwitchboardOperatorInstruction,
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

        tracer = trace.get_tracer("brain.agent")
        manager = tracer.start_as_current_span("agent.turn")
        span = manager.__enter__()
        self._manager = manager
        self._span = span
        observation_input = _operator_observation_input(
            system_blocks=self._runtime.system_blocks,
            instruction=self._instruction,
        )
        input_json = _json_dumps_or_empty(observation_input)
        _set_span_attributes(
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
                "langfuse.observation.metadata.operation": "agent.turn",
                "brain.operation": "agent.turn",
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
            _set_span_attributes(
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
    """Attach MAS-resolved session identifiers to the root turn span."""
    if span is None:
        return
    session_id = runtime.turn_state.conversation_episode_id or runtime.session_id
    _set_span_attributes(
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
    _set_span_attributes(
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
_COMPRESS_USER_PROMPT_TEMPLATE_KEYS = frozenset(
    _PROMPT_TEMPLATE_VAR_RE.findall(_COMPRESS_USER_PROMPT_TEMPLATE)
)
if _COMPRESS_USER_PROMPT_TEMPLATE_KEYS != {
    "tool_name",
    "call_mode",
    "intent",
    "raw_output",
}:
    raise ValueError(
        "compress-tool-return-user-template.txt must contain exactly "
        "{{tool_name}}, {{call_mode}}, {{intent}}, and {{raw_output}}"
    )


def _render_prompt_template(template: str, /, **values: str) -> str:
    """Render one prompt template and reject unresolved placeholders."""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            return match.group(0)
        return values[key]

    rendered = _PROMPT_TEMPLATE_VAR_RE.sub(_replace, template)
    unresolved = _PROMPT_TEMPLATE_VAR_RE.findall(rendered)
    if unresolved:
        raise ValueError(
            f"unresolved prompt template placeholders: {', '.join(sorted(unresolved))}"
        )
    return rendered


def _call_with_optional_meta(func, /, *, meta: MetaOverrides | None, **kwargs: Any):
    """Call one SDK-style method while tolerating legacy fake client signatures."""
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


@dataclass(frozen=True, slots=True)
class _PendingInvocation:
    """Short-lived record for one approval-gated capability attempt."""

    proposal_token: str
    capability_id: str
    input_payload: dict[str, object]
    actor: str
    channel: str
    requires_approval: bool
    reason_codes: tuple[str, ...]
    created_at: datetime
    expires_at: datetime | None = None


@dataclass(slots=True)
class _TurnState:
    """Mutable turn-local metadata shared by capability tool wrappers."""

    actor: str = "operator"
    channel: str = ""
    trace_id: str = ""
    conversation_episode_id: str = ""
    root_envelope_id: str = ""
    current_model_envelope_id: str = ""
    always_on_capability_ids: frozenset[str] = frozenset()
    denied_capability_ids: frozenset[str] = frozenset()
    active_tool_names: set[str] = field(default_factory=set)
    frozen_tool_names: tuple[str, ...] = ()
    tools_frozen: bool = False
    pending_invocations: dict[str, _PendingInvocation] = field(default_factory=dict)
    reply_to_proposal_token: str = ""
    reaction_to_proposal_token: str = ""
    lms_recovery_notice_sent: bool = False

    def reset_active_tools(self) -> None:
        """Reset the active tool set to the always-on CES tools plus runtime tools."""
        self.tools_frozen = False
        self.frozen_tool_names = ()
        self.active_tool_names = {
            *(
                capability_id
                for capability_id in self.always_on_capability_ids
                if capability_id not in self.denied_capability_ids
            ),
            _SEARCH_TOOLS_TOOL_NAME,
            _GET_TOOL_INFO_TOOL_NAME,
        }

    def prune_pending_invocations(self, *, now: datetime | None = None) -> None:
        """Evict expired and oldest pending approval records."""
        effective_now = now or datetime.now(UTC)
        expired_tokens = [
            token
            for token, pending in self.pending_invocations.items()
            if pending.expires_at is not None and pending.expires_at <= effective_now
        ]
        for token in expired_tokens:
            self.pending_invocations.pop(token, None)

        overflow = len(self.pending_invocations) - _MAX_PENDING_INVOCATIONS
        if overflow <= 0:
            return

        oldest_tokens = [
            token
            for token, _pending in sorted(
                self.pending_invocations.items(),
                key=lambda item: item[1].created_at,
            )[:overflow]
        ]
        for token in oldest_tokens:
            self.pending_invocations.pop(token, None)

    def remember_pending_invocation(
        self,
        *,
        proposal_token: str,
        capability_id: str,
        input_payload: dict[str, object],
        requires_approval: bool,
        reason_codes: tuple[str, ...],
        expires_at: datetime | None = None,
        now: datetime | None = None,
    ) -> None:
        """Persist one short-lived approval-gated invocation attempt."""
        token = proposal_token.strip()
        if token == "":
            return

        effective_now = now or datetime.now(UTC)
        self.prune_pending_invocations(now=effective_now)
        self.pending_invocations[token] = _PendingInvocation(
            proposal_token=token,
            capability_id=capability_id,
            input_payload=dict(input_payload),
            actor=self.actor,
            channel=self.channel,
            requires_approval=requires_approval,
            reason_codes=reason_codes,
            created_at=effective_now,
            expires_at=expires_at,
        )
        self.prune_pending_invocations(now=effective_now)

    def proposal_token_for_retry(
        self,
        *,
        capability_id: str,
        input_payload: dict[str, object],
    ) -> tuple[str, str]:
        """Return matched reply/reaction proposal correlators for one safe retry."""
        reply_token = self.reply_to_proposal_token.strip()
        reaction_token = self.reaction_to_proposal_token.strip()
        matched_reply = self._matching_pending_token(
            proposal_token=reply_token,
            capability_id=capability_id,
            input_payload=input_payload,
        )
        matched_reaction = self._matching_pending_token(
            proposal_token=reaction_token,
            capability_id=capability_id,
            input_payload=input_payload,
        )
        return matched_reply, matched_reaction

    def _matching_pending_token(
        self,
        *,
        proposal_token: str,
        capability_id: str,
        input_payload: dict[str, object],
    ) -> str:
        """Return one proposal token only when it matches a stored blocked invocation."""
        token = proposal_token.strip()
        if token == "":
            return ""
        pending = self.pending_invocations.get(token)
        if pending is None:
            return ""
        if pending.capability_id != capability_id:
            return ""
        if pending.input_payload != input_payload:
            return ""
        return token

    def begin_turn_trace(self) -> None:
        """Start one fresh trace context for the current operator turn."""
        self.trace_id = generate_ulid_str()
        self.root_envelope_id = generate_ulid_str()
        self.current_model_envelope_id = ""
        self.lms_recovery_notice_sent = False

    def next_model_meta(self) -> MetaOverrides:
        """Allocate metadata for one LMS request within the active turn trace."""
        envelope_id = generate_ulid_str()
        self.current_model_envelope_id = envelope_id
        return MetaOverrides(
            trace_id=self.trace_id or None,
            parent_id=self.root_envelope_id,
            envelope_id=envelope_id,
        )

    def nested_call_meta(self) -> MetaOverrides | None:
        """Return metadata for one nested SDK call under the current model node."""
        if self.trace_id == "":
            return None
        return MetaOverrides(
            trace_id=self.trace_id,
            parent_id=self.current_model_envelope_id or self.root_envelope_id,
        )


@dataclass(slots=True)
class _AgentRuntime:
    """Assembled agent runtime dependencies created once at startup."""

    client: BrainClient
    session_id: str
    turn_state: _TurnState
    model: "_BrainSdkToolModel"
    agent: Agent[None, str]
    lms_request_timeout_seconds: float
    preferred_timezone: str = "UTC"
    system_blocks: tuple[InferenceSystemBlock, ...] = ()
    environment_context_entries: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class _CompressedToolReturn:
    """Result of one secondary LMS compression call for a tool return."""

    content: str
    model: str
    provider: str


@dataclass(frozen=True, slots=True)
class _NormalizedToolReturn:
    """Display-safe tool return plus audit metadata for one tool execution."""

    content: str
    normalization_kind: str
    raw_content: str
    raw_char_count: int
    final_char_count: int
    compressed_by_model: str = ""
    compressed_by_provider: str = ""


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


def _resolve_core_config_path() -> Path | None:
    """Return an explicit core config path when the env override is set."""
    value = os.getenv("BRAIN_CORE_CONFIG_FILE", "").strip()
    if value == "":
        return None
    return Path(value)


def _resolve_resources_config_path() -> Path | None:
    """Return an explicit resources config path when the env override is set."""
    value = os.getenv("BRAIN_RESOURCES_CONFIG_FILE", "").strip()
    if value == "":
        return None
    return Path(value)


def _load_startup_settings() -> tuple[ActorSettings, CoreRuntimeSettings]:
    """Load actor and core/resources settings using explicit env-overridden paths."""
    settings = load_actor_settings(config_path=_resolve_config_path())
    core_runtime_settings = load_core_runtime_settings(
        core_config_path=_resolve_core_config_path(),
        resources_config_path=_resolve_resources_config_path(),
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

    configure_logging(
        level=str(settings.logging.level),
        file_capture_enabled=settings.logging.file_capture_enabled,
        file_capture_level=str(settings.logging.file_capture_level),
        file_capture_directory=settings.logging.file_capture_directory,
        json_output=bool(settings.logging.json_output),
        process_name=str(settings.logging.process_name),
        environment=str(settings.logging.environment),
    )


class _BrainSdkToolModel(Model):
    """PydanticAI model backed by the Brain SDK tool-capable LMS endpoint."""

    def __init__(
        self,
        *,
        client: BrainClient,
        turn_state: _TurnState | None = None,
        profile_name: str = "standard",
        timeout_seconds: float | None = None,
        session_id: str,
        source: str,
        principal: str,
        system_blocks: tuple[InferenceSystemBlock, ...],
        tool_requires_approval: dict[str, bool | None] | None = None,
    ) -> None:
        super().__init__(profile=ModelProfile(supports_tools=True))
        self._client = client
        self._turn_state = _TurnState() if turn_state is None else turn_state
        self._profile_name = profile_name
        self._timeout_seconds = timeout_seconds
        self._session_id = session_id
        self._source = source
        self._principal = principal
        self._system_blocks = system_blocks
        self._tool_requires_approval = (
            {} if tool_requires_approval is None else dict(tool_requires_approval)
        )
        self.last_result: LmsToolChatResult | None = None
        self._last_used_profile_name = profile_name

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
        request_meta = self._turn_state.next_model_meta()
        original_profile_name = self.profile_name
        cumulative_retry_delay_seconds = 0.0
        advertised_tool_names = [item.name for item in prepared_params.function_tools]
        last_exc: BrainSdkError | None = None

        def _recovery_notice_due(*, profile_index: int, next_delay: float) -> bool:
            if self._turn_state.lms_recovery_notice_sent:
                return False
            if profile_index > 0:
                return True
            return (
                cumulative_retry_delay_seconds + next_delay
                >= _LMS_RECOVERY_NOTICE_DELAY_THRESHOLD_SECONDS
            )

        try:
            for profile_index, profile_name in enumerate(
                _lms_recovery_profile_sequence(original_profile_name)
            ):
                self.set_profile_name(profile_name)
                for provider_attempt in range(
                    len(_LMS_PROVIDER_RETRY_DELAYS_SECONDS) + 1
                ):
                    system_blocks = self._system_blocks
                    result: LmsToolChatResult | None = None
                    valid_tool_calls: tuple[LmsChatToolCall, ...] = ()
                    invalid_tool_names: tuple[str, ...] = ()
                    try:
                        for repair_attempt in range(_INVALID_TOOL_CALL_REPAIR_ATTEMPTS):
                            inference_request = _build_inference_request(
                                session_id=self._session_id,
                                conversation_episode_id=self._turn_state.conversation_episode_id,
                                source=self._source,
                                principal=self._principal,
                                meta=request_meta,
                                system_blocks=system_blocks,
                                messages=messages,
                                tool_defs=prepared_params.function_tools,
                                allow_text_output=prepared_params.allow_text_output,
                                allow_parallel_tool_calls=_allow_parallel_tool_calls(
                                    messages=messages
                                ),
                                profile=self.profile_name,
                                tool_requires_approval=self._tool_requires_approval,
                            )
                            result = await asyncio.to_thread(
                                _call_with_optional_meta,
                                self._client.lms_chat_with_tools,
                                meta=request_meta,
                                inference_request=inference_request,
                                timeout_seconds=self._timeout_seconds,
                            )
                            valid_tool_calls, invalid_tool_names = (
                                _partition_returned_tool_calls(
                                    tool_calls=result.tool_calls,
                                    advertised_tool_defs=prepared_params.function_tools,
                                )
                            )
                            if len(invalid_tool_names) == 0:
                                break
                            _LOGGER.warning(
                                "brain agent model returned unadvertised tool calls",
                                extra={
                                    "invalid_tool_names": list(invalid_tool_names),
                                    "advertised_tool_names": advertised_tool_names,
                                    "repair_attempt": repair_attempt + 1,
                                    "profile": self.profile_name,
                                },
                            )
                            if len(valid_tool_calls) > 0 or repair_attempt >= (
                                _INVALID_TOOL_CALL_REPAIR_ATTEMPTS - 1
                            ):
                                break
                            system_blocks = (
                                *self._system_blocks,
                                InferenceSystemBlock(
                                    kind="instructions",
                                    text=_INVALID_TOOL_CALL_RETRY_INSTRUCTION,
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
                                        retryable=True,
                                        metadata={
                                            "tool_names": ",".join(invalid_tool_names)
                                        },
                                    ),
                                ),
                            )
                        parts: list[TextPart | ToolCallPart] = []
                        if result.text is not None and result.text.strip() != "":
                            parts.append(TextPart(result.text.strip()))
                        parts.extend(
                            _to_model_tool_call(item) for item in valid_tool_calls
                        )
                        if len(parts) == 0:
                            parts.append(TextPart("I do not have a response yet."))
                        self._last_used_profile_name = self.profile_name
                        _set_current_span_attributes(
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
                            finish_reason=_normalize_finish_reason(
                                result.finish_reason
                            ),
                        )
                    except BrainSdkError as exc:
                        if not _should_retry_lms_failure(exc):
                            raise
                        last_exc = exc
                        is_last_provider_attempt = provider_attempt >= len(
                            _LMS_PROVIDER_RETRY_DELAYS_SECONDS
                        )
                        should_notify = _should_notify_operator_of_lms_recovery(exc)
                        if should_notify and _recovery_notice_due(
                            profile_index=profile_index,
                            next_delay=(
                                0.0
                                if is_last_provider_attempt
                                else _LMS_PROVIDER_RETRY_DELAYS_SECONDS[
                                    provider_attempt
                                ]
                            ),
                        ):
                            await _notify_operator_of_lms_recovery(
                                client=self._client,
                                turn_state=self._turn_state,
                                session_id=self._session_id,
                                message=_LMS_RECOVERY_IN_PROGRESS_RESPONSE,
                                reasoning_level=self.profile_name,
                            )
                            self._turn_state.lms_recovery_notice_sent = True
                        if is_last_provider_attempt:
                            break
                        retry_delay_seconds = (
                            _LMS_PROVIDER_RETRY_DELAYS_SECONDS[provider_attempt]
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
        """Return the active LMS profile name for this agent turn."""
        value = getattr(self, "_profile_name", "")
        return value if isinstance(value, str) and value != "" else "standard"

    def set_profile_name(self, profile_name: str) -> None:
        """Update the active LMS profile name for subsequent requests."""
        self._profile_name = profile_name

    @property
    def last_used_profile_name(self) -> str:
        """Return the profile that produced the latest successful model response."""
        value = getattr(self, "_last_used_profile_name", "")
        return value if isinstance(value, str) and value != "" else self.profile_name


_CONTENT_PART_TYPES = (
    str,
    CachePoint,
    TextContentPart,
    CachePointContentPart,
    FocusContentPart,
    ConversationSummaryContentPart,
    DialogueTurnContentPart,
    ReferenceSnippetContentPart,
    EnvironmentContextContentPart,
    OperatorMessageContentPart,
)


def _stringify_content(value: object) -> str:
    """Render one structured content value into a stable compact string."""
    if isinstance(value, str):
        return value
    if isinstance(value, list | tuple):
        if all(isinstance(item, _CONTENT_PART_TYPES) for item in value):
            parts: list[str] = []
            for item in value:
                if isinstance(item, CachePoint):
                    continue
                parts.append(_stringify_content(item))
            return "".join(parts)
        try:
            return json.dumps(value, sort_keys=True)
        except TypeError:
            return str(value)
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)


def _content_has_cache_point(value: object) -> bool:
    """Return whether one structured user-content payload already includes cache."""
    if isinstance(value, CachePoint):
        return True
    if isinstance(value, list | tuple):
        return any(_content_has_cache_point(item) for item in value)
    return False


def _build_inference_request(
    *,
    session_id: str,
    conversation_episode_id: str,
    source: str,
    principal: str,
    meta: MetaOverrides | None,
    system_blocks: tuple[InferenceSystemBlock, ...],
    messages: list[ModelRequest | ModelResponse],
    tool_defs: list[ToolDefinition],
    allow_text_output: bool,
    allow_parallel_tool_calls: bool = True,
    profile: str,
    tool_requires_approval: dict[str, bool | None],
) -> InferenceRequest:
    """Build one canonical inference request from PydanticAI history + runtime state."""
    explicit_cache = False
    context_found = False
    current_focus: str | None = None
    recent_conversation_summary = ""
    recent_turns: list[InferenceMemoryTurn] = []
    reference_snippets: list[InferenceReferenceSnippet] = []
    environment_context = InferenceEnvironmentContext()
    operator_message: InferenceOperatorMessage | None = None
    live_events: list[
        InferenceAssistantTextEvent
        | InferenceToolCallBatchEvent
        | InferenceToolResultBatchEvent
    ] = []

    for message in messages:
        if isinstance(message, ModelRequest):
            tool_results: list[InferenceToolResult] = []
            tool_results_cache_after = False
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    content_parts = _to_content_parts(part.content)
                    if any(
                        isinstance(item, CachePointContentPart)
                        for item in content_parts
                    ):
                        explicit_cache = True
                    if not context_found and _contains_context_content_parts(
                        content_parts
                    ):
                        (
                            current_focus,
                            recent_conversation_summary,
                            recent_turns,
                            reference_snippets,
                            environment_context,
                            operator_message,
                        ) = _extract_context_from_content_parts(content_parts)
                        context_found = True
                        continue
                    if _content_parts_are_only_cache_points(content_parts):
                        if len(tool_results) > 0:
                            tool_results_cache_after = True
                        else:
                            _mark_cache_after_last_live_event(live_events)
                        continue
                    if operator_message is None and len(content_parts) > 0:
                        fallback_text = _text_from_content_parts(content_parts).strip()
                        if fallback_text != "":
                            operator_message = InferenceOperatorMessage(
                                channel="",
                                sender_e164="",
                                message_text=fallback_text,
                            )
                    continue
                if isinstance(part, ToolReturnPart):
                    tool_results.append(_tool_return_part_to_inference_result(part))
            if len(tool_results) > 0:
                live_events.append(
                    InferenceToolResultBatchEvent(
                        results=tuple(tool_results),
                        cache_after=tool_results_cache_after,
                    )
                )
            continue

        text_segments: list[str] = []
        tool_calls: list[InferenceToolCall] = []
        for part in message.parts:
            if isinstance(part, TextPart):
                text_segments.append(part.content)
            elif isinstance(part, ToolCallPart):
                tool_calls.append(
                    InferenceToolCall(
                        call_id=part.tool_call_id,
                        tool_name=part.tool_name,
                        arguments=_tool_args_object(part.args),
                    )
                )
        if len(text_segments) > 0:
            live_events.append(
                InferenceAssistantTextEvent(text="\n".join(text_segments))
            )
        if len(tool_calls) > 0:
            live_events.append(InferenceToolCallBatchEvent(calls=tuple(tool_calls)))

    if operator_message is None:
        operator_message = InferenceOperatorMessage(
            channel="",
            sender_e164="",
            message_text="",
        )

    return InferenceRequest(
        meta=InferenceMeta(
            trace_id="" if meta is None or meta.trace_id is None else meta.trace_id,
            session_id=session_id,
            conversation_episode_id=conversation_episode_id,
            source=source,
            principal=principal,
            envelope_id=""
            if meta is None or meta.envelope_id is None
            else meta.envelope_id,
            parent_id="" if meta is None or meta.parent_id is None else meta.parent_id,
        ),
        system=InferenceSystem(blocks=system_blocks),
        memory_context=InferenceMemoryContext(
            current_focus=current_focus,
            recent_conversation_summary=recent_conversation_summary,
            recent_turns=tuple(recent_turns),
            reference_snippets=tuple(reference_snippets),
        ),
        environment_context=environment_context,
        current_turn=InferenceCurrentTurn(operator_message=operator_message),
        tools=tuple(
            _to_inference_tool_definition(
                item,
                requires_approval=tool_requires_approval.get(item.name),
            )
            for item in tool_defs
        ),
        live_events=tuple(live_events),
        controls=InferenceControls(
            allow_text_output=allow_text_output,
            tool_choice=InferenceToolChoice(mode="auto"),
            parallel_tool_calls=InferenceParallelToolCalls(
                mode="allow" if allow_parallel_tool_calls else "forbid"
            ),
            profile=profile if profile in {"quick", "standard", "deep"} else None,
        ),
        cache=InferenceCache(mode="explicit" if explicit_cache else "none"),
    )


def _contains_context_content_parts(parts: tuple[ChatContentPart, ...]) -> bool:
    """Return True when one content-part tuple encodes the initial context payload."""
    return any(
        isinstance(
            item,
            FocusContentPart
            | ConversationSummaryContentPart
            | DialogueTurnContentPart
            | ReferenceSnippetContentPart
            | EnvironmentContextContentPart
            | OperatorMessageContentPart,
        )
        for item in parts
    )


def _content_parts_are_only_cache_points(parts: tuple[ChatContentPart, ...]) -> bool:
    """Return True when a user prompt contains only structural cache markers."""
    return len(parts) > 0 and all(
        isinstance(item, CachePointContentPart) for item in parts
    )


def _extract_context_from_content_parts(
    parts: tuple[ChatContentPart, ...],
) -> tuple[
    str | None,
    str,
    list[InferenceMemoryTurn],
    list[InferenceReferenceSnippet],
    InferenceEnvironmentContext,
    InferenceOperatorMessage | None,
]:
    """Extract canonical memory + current-turn data from structured prompt parts."""
    current_focus: str | None = None
    recent_conversation_summary = ""
    recent_turns: list[InferenceMemoryTurn] = []
    reference_snippets: list[InferenceReferenceSnippet] = []
    environment_items: list[InferenceEnvironmentItem] = []
    operator_message: InferenceOperatorMessage | None = None
    fallback_text_parts: list[str] = []

    for item in parts:
        if isinstance(item, FocusContentPart):
            current_focus = None if item.text == "" else item.text
        elif isinstance(item, ConversationSummaryContentPart):
            recent_conversation_summary = item.text
        elif isinstance(item, DialogueTurnContentPart):
            if item.role in {"user", "assistant"}:
                recent_turns.append(
                    InferenceMemoryTurn(
                        role=item.role,
                        text=item.text,
                        is_summary=item.is_summary,
                    )
                )
        elif isinstance(item, ReferenceSnippetContentPart):
            reference_snippets.append(InferenceReferenceSnippet(text=item.text))
        elif isinstance(item, EnvironmentContextContentPart):
            environment_items.extend(item.items)
        elif isinstance(item, OperatorMessageContentPart):
            operator_message = InferenceOperatorMessage(
                channel=item.channel,
                sender_e164=item.sender_e164,
                message_text=item.message_text,
                approval_intent=item.approval_intent,
                reaction_emoji=item.reaction_emoji,
                quote_target_timestamp_ms=item.quote_target_timestamp_ms,
                reaction_target_timestamp_ms=item.reaction_target_timestamp_ms,
                reply_to_proposal_token=item.reply_to_proposal_token,
                reaction_to_proposal_token=item.reaction_to_proposal_token,
            )
        elif isinstance(item, TextContentPart):
            fallback_text_parts.append(item.text)

    if operator_message is None and len(fallback_text_parts) > 0:
        operator_message = InferenceOperatorMessage(
            channel="",
            sender_e164="",
            message_text="\n".join(fallback_text_parts),
        )
    return (
        current_focus,
        recent_conversation_summary,
        recent_turns,
        reference_snippets,
        InferenceEnvironmentContext(items=tuple(environment_items)),
        operator_message,
    )


def _text_from_content_parts(parts: tuple[ChatContentPart, ...]) -> str:
    """Render only text-bearing content parts into one fallback string."""
    segments: list[str] = []
    for item in parts:
        if isinstance(item, TextContentPart):
            segments.append(item.text)
    return "\n".join(segment for segment in segments if segment != "")


def _mark_cache_after_last_live_event(
    events: list[
        InferenceAssistantTextEvent
        | InferenceToolCallBatchEvent
        | InferenceToolResultBatchEvent
    ],
) -> None:
    """Mark the last live event as a cache boundary when one exists."""
    if len(events) == 0:
        return
    events[-1] = events[-1].model_copy(update={"cache_after": True})


def _to_content_parts(value: object) -> tuple[ChatContentPart, ...]:
    """Convert one PydanticAI content payload into canonical chat content parts."""
    if isinstance(value, str):
        if value == "":
            return ()
        return (TextContentPart(text=value),)
    if isinstance(value, CachePoint):
        return (CachePointContentPart(),)
    if isinstance(
        value,
        TextContentPart
        | CachePointContentPart
        | FocusContentPart
        | ConversationSummaryContentPart
        | DialogueTurnContentPart
        | ReferenceSnippetContentPart
        | EnvironmentContextContentPart
        | OperatorMessageContentPart,
    ):
        return (value,)
    if isinstance(value, list | tuple):
        if all(isinstance(item, _CONTENT_PART_TYPES) for item in value):
            parts: list[ChatContentPart] = []
            for item in value:
                parts.extend(_to_content_parts(item))
            return tuple(parts)
        rendered = _stringify_content(value)
        if rendered == "":
            return ()
        return (TextContentPart(text=rendered),)
    rendered = _stringify_content(value)
    if rendered == "":
        return ()
    return (TextContentPart(text=rendered),)


def _tool_args_json(value: str | dict[str, object] | None) -> str:
    """Convert one tool-call args payload into canonical JSON text."""
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def _tool_args_object(value: str | dict[str, object] | None) -> dict[str, object]:
    """Convert one tool-call args payload into canonical structured object form."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        payload = json.loads(value)
    except ValueError:
        return {"raw_args_json": value}
    return payload if isinstance(payload, dict) else {"raw_args_json": value}


def _tool_return_part_to_inference_result(part: ToolReturnPart) -> InferenceToolResult:
    """Convert one tool return part into a canonical structured tool result."""
    status = _classify_tool_result_status(part.content)
    payload = _tool_result_payload_from_content(part.content)
    return InferenceToolResult(
        call_id=part.tool_call_id,
        tool_name=part.tool_name,
        status=status,
        is_error=(status == "error"),
        result=payload,
    )


def _classify_tool_result_status(
    value: object,
) -> Literal["success", "empty", "error"]:
    """Classify one tool result as success, empty, or error."""
    if _is_tool_error_payload(value):
        return "error"
    if _is_empty_tool_result(value):
        return "empty"
    return "success"


def _is_tool_error_payload(value: object) -> bool:
    """Return True when one tool result matches the agent error payload shape."""
    if isinstance(value, dict):
        return (
            isinstance(value.get("error"), str)
            and isinstance(value.get("message"), str)
            and isinstance(value.get("capability_id"), str)
        )
    if not isinstance(value, str):
        return False
    try:
        payload = json.loads(value)
    except ValueError:
        return False
    return isinstance(payload, dict) and _is_tool_error_payload(payload)


def _is_empty_tool_result(value: object) -> bool:
    """Return True when one tool result is semantically empty but not erroneous."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in {"", "null", "[]", "{}"}
    if isinstance(value, list | tuple | dict | set | frozenset):
        return len(value) == 0
    return False


def _tool_result_payload_from_content(value: object) -> InferenceToolResultPayload:
    """Convert one arbitrary tool result into canonical structured payload fields."""
    if value is None:
        return InferenceToolResultPayload(mime_type="text/plain", text="")
    if isinstance(value, str):
        if _is_empty_tool_result(value):
            return InferenceToolResultPayload(mime_type="text/plain", text="")
        return InferenceToolResultPayload(mime_type="text/plain", text=value)
    if isinstance(value, dict | list | tuple):
        if _is_empty_tool_result(value):
            return InferenceToolResultPayload(
                mime_type="application/json",
                data=value,
            )
        return InferenceToolResultPayload(
            mime_type="application/json",
            data=value,
        )
    return InferenceToolResultPayload(
        mime_type="text/plain",
        text=_stringify_content(value),
    )


def _is_not_found_tool_result(value: object) -> bool:
    """Return True when one tool result encodes a not-found style failure."""
    payload = value
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except ValueError:
            return False
    if not isinstance(payload, dict):
        return False
    if str(payload.get("error", "")).strip() == "not_found":
        return True
    details = payload.get("details")
    if not isinstance(details, list):
        return False
    for item in details:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", "")).strip()
        code = str(item.get("code", "")).strip()
        if category == "not_found" or code == "RESOURCE_NOT_FOUND":
            return True
    return False


def _estimate_uncached_delta_tokens(
    messages: list[ModelRequest | ModelResponse],
) -> int:
    """Estimate token growth since the most recent explicit cachepoint."""
    segments: list[str] = []

    def append_text(text: str) -> None:
        normalized = text.strip()
        if normalized != "":
            segments.append(normalized)

    def reset_segments() -> None:
        segments.clear()

    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart):
                    for content_part in _to_content_parts(part.content):
                        if isinstance(content_part, CachePointContentPart):
                            reset_segments()
                            continue
                        append_text(_stringify_content(content_part))
                    continue
                if isinstance(part, ToolReturnPart):
                    append_text(part.tool_name)
                    append_text(_stringify_content(part.content))
                    continue
                system_prompt = getattr(part, "content", None)
                if isinstance(system_prompt, str):
                    append_text(system_prompt)
            continue
        for part in message.parts:
            if isinstance(part, TextPart):
                append_text(part.content)
            elif isinstance(part, ToolCallPart):
                append_text(part.tool_name)
                append_text(_tool_args_json(part.args))
    return _estimate_token_count("\n".join(segments))


def _rolling_cache_expected_reuses(
    *,
    tool_returns: list[ToolReturnPart],
    call_args_by_id: dict[str, dict[str, object]],
    hop_count: int,
) -> float:
    """Estimate expected future compatible reuses for one rolling cachepoint."""
    if len(tool_returns) == 0:
        return 0.0
    total = float(len(tool_returns))
    explore_count = 0.0
    discovery_count = 0.0
    failure_count = 0.0
    not_found_count = 0.0
    decisive_success_count = 0.0

    for part in tool_returns:
        call_args = call_args_by_id.get(part.tool_call_id, {})
        call_mode = str(call_args.get("call_mode", "explore")).strip() or "explore"
        status = _classify_tool_result_status(part.content)
        if call_mode == "explore":
            explore_count += 1.0
        if part.tool_name in _DISCOVERY_TOOL_NAMES:
            discovery_count += 1.0
        if status in {"error", "empty"}:
            failure_count += 1.0
        if _is_not_found_tool_result(part.content):
            not_found_count += 1.0
        if call_mode == "decide" and status == "success":
            decisive_success_count += 1.0

    continuation_probability = _ROLLING_CACHE_BASE_CONTINUATION_PROBABILITY
    continuation_probability += _ROLLING_CACHE_EXPLORE_WEIGHT * (explore_count / total)
    continuation_probability += _ROLLING_CACHE_DISCOVERY_WEIGHT * (
        discovery_count / total
    )
    continuation_probability += _ROLLING_CACHE_FAILURE_WEIGHT * (failure_count / total)
    continuation_probability += _ROLLING_CACHE_NOT_FOUND_WEIGHT * (
        not_found_count / total
    )
    continuation_probability += _ROLLING_CACHE_DECISIVE_SUCCESS_WEIGHT * (
        decisive_success_count / total
    )
    continuation_probability += _ROLLING_CACHE_HOP_DECAY * max(0.0, hop_count - 3.0)
    continuation_probability = max(
        _ROLLING_CACHE_MIN_PROBABILITY,
        min(_ROLLING_CACHE_MAX_PROBABILITY, continuation_probability),
    )

    expected_reuses = 0.0
    for power in range(1, _ROLLING_CACHE_MAX_FUTURE_REUSES + 1):
        expected_reuses += continuation_probability**power
    return expected_reuses


def _rolling_cachepoint_score(
    *,
    tool_returns: list[ToolReturnPart],
    call_args_by_id: dict[str, dict[str, object]],
    hop_count: int,
    candidate_messages: list[ModelRequest | ModelResponse],
) -> float:
    """Return one concrete Anthropic price-weighted score for a rolling cachepoint."""
    delta_tokens = _estimate_uncached_delta_tokens(candidate_messages)
    expected_reuses = _rolling_cache_expected_reuses(
        tool_returns=tool_returns,
        call_args_by_id=call_args_by_id,
        hop_count=hop_count,
    )
    return float(delta_tokens) * ((0.90 * expected_reuses) - 0.25)


def _tool_schema_with_agent_context(schema: dict[str, object]) -> dict[str, object]:
    """Return one tool schema augmented with agent-only context properties."""
    properties = schema.get("properties", {})
    merged_properties = (
        {**properties, **_AGENT_CONTEXT_PROPERTIES}
        if isinstance(properties, dict)
        else dict(_AGENT_CONTEXT_PROPERTIES)
    )
    return {
        **schema,
        "properties": merged_properties,
        "additionalProperties": False,
    }


def _to_inference_tool_definition(
    value: ToolDefinition,
    *,
    requires_approval: bool | None,
) -> InferenceToolDefinition:
    """Convert one PydanticAI tool definition into a canonical inference tool."""
    return InferenceToolDefinition(
        name=value.name,
        input_schema=_tool_schema_with_agent_context(
            dict(value.parameters_json_schema)
        ),
        description=value.description,
        strict_schema=value.strict,
        execution_hints=InferenceToolExecutionHints(
            sequential=value.sequential,
            requires_approval=requires_approval,
        ),
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


def _partition_returned_tool_calls(
    *,
    tool_calls: tuple[LmsChatToolCall, ...],
    advertised_tool_defs: list[ToolDefinition],
) -> tuple[tuple[LmsChatToolCall, ...], tuple[str, ...]]:
    """Split returned tool calls into advertised-valid and invalid subsets."""
    advertised_tool_names = {item.name for item in advertised_tool_defs}
    valid_tool_calls = tuple(
        item for item in tool_calls if item.tool_name in advertised_tool_names
    )
    invalid_tool_names = tuple(
        sorted(
            {
                item.tool_name
                for item in tool_calls
                if item.tool_name not in advertised_tool_names
            }
        )
    )
    return valid_tool_calls, invalid_tool_names


def _allow_parallel_tool_calls(*, messages: list[ModelRequest | ModelResponse]) -> bool:
    """Return whether the current hop can safely permit parallel tool calls."""
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        saw_tool_return = False
        for part in message.parts:
            if not isinstance(part, ToolReturnPart):
                continue
            saw_tool_return = True
            if part.tool_name in {_SEARCH_TOOLS_TOOL_NAME, _GET_TOOL_INFO_TOOL_NAME}:
                return False
        if saw_tool_return:
            return True
    return True


def _parse_optional_iso_datetime(value: object) -> datetime | None:
    """Parse one optional ISO-8601 datetime string from policy metadata."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized == "":
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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
            _requires_approval: bool = descriptor.requires_approval,
            **input_payload: object,
        ) -> object:
            # Strip agent-only context properties before forwarding to the capability.
            capability_payload = {
                k: v
                for k, v in input_payload.items()
                if k not in _AGENT_CONTEXT_PROPERTIES
            }
            reply_token, reaction_token = turn_state.proposal_token_for_retry(
                capability_id=_capability_id,
                input_payload=capability_payload,
            )
            try:
                result = _call_with_optional_meta(
                    client.invoke_capability,
                    meta=turn_state.nested_call_meta(),
                    capability_id=_capability_id,
                    input_payload=capability_payload,
                    actor=turn_state.actor,
                    channel=turn_state.channel,
                    reply_to_proposal_token=reply_token,
                    reaction_to_proposal_token=reaction_token,
                )
            except BrainPolicyError as exc:
                metadata = (
                    {} if len(exc.details) == 0 else dict(exc.details[0].metadata)
                )
                reason_codes = [
                    item
                    for item in metadata.get("reason_codes", "").split(",")
                    if item != ""
                ]
                proposal_token = str(metadata.get("proposal_token", "")).strip()
                expires_at = _parse_optional_iso_datetime(metadata.get("expires_at"))
                if proposal_token != "":
                    turn_state.remember_pending_invocation(
                        proposal_token=proposal_token,
                        capability_id=_capability_id,
                        input_payload=capability_payload,
                        requires_approval=_requires_approval,
                        reason_codes=tuple(reason_codes),
                        expires_at=expires_at,
                    )
                return {
                    "error": "policy_denied",
                    "message": str(exc),
                    "capability_id": _capability_id,
                    "requires_approval": _requires_approval,
                    "proposal_token": proposal_token,
                    "proposal_expires_at": (
                        "" if expires_at is None else expires_at.isoformat()
                    ),
                    "reason_codes": reason_codes,
                }
            except BrainValidationError as exc:
                return _capability_error_payload(
                    error="validation_error",
                    capability_id=_capability_id,
                    exc=exc,
                )
            except BrainConflictError as exc:
                return _capability_error_payload(
                    error="conflict_error",
                    capability_id=_capability_id,
                    exc=exc,
                )
            except BrainNotFoundError as exc:
                return _capability_error_payload(
                    error="not_found",
                    capability_id=_capability_id,
                    exc=exc,
                )
            except BrainDependencyError as exc:
                return _capability_error_payload(
                    error="dependency_error",
                    capability_id=_capability_id,
                    exc=exc,
                )
            except BrainInternalError as exc:
                _LOGGER.error(
                    "brain agent capability tool internal error",
                    extra={"capability_id": _capability_id},
                )
                return _capability_error_payload(
                    error="internal_error",
                    capability_id=_capability_id,
                    exc=exc,
                )
            except BrainDomainError as exc:
                return _capability_error_payload(
                    error="domain_error",
                    capability_id=_capability_id,
                    exc=exc,
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


def _capability_error_payload(
    *,
    error: str,
    capability_id: str,
    exc: BrainDomainError,
) -> dict[str, object]:
    """Return one stable tool error payload for SDK domain failures."""
    return {
        "error": error,
        "message": str(exc),
        "capability_id": capability_id,
        "details": [
            {
                "code": item.code,
                "message": item.message,
                "category": item.category,
                "retryable": item.retryable,
                "metadata": dict(item.metadata),
            }
            for item in exc.details
        ],
    }


def _build_runtime_tools(
    *,
    client: BrainClient,
    turn_state: _TurnState,
) -> list[Tool[None]]:
    """Create hardcoded runtime discovery tools for dynamic capability exposure."""

    def _search_tools(
        query: str,
        limit: int | None = None,
        call_mode: str = "explore",
        response_detail: str = "",
    ) -> list[dict[str, object]]:
        del call_mode, response_detail
        results = _call_with_optional_meta(
            client.search_capabilities,
            meta=turn_state.nested_call_meta(),
            query=query,
            limit=limit,
        )
        visible_results = [
            item
            for item in results
            if item.capability_id not in turn_state.denied_capability_ids
        ]
        return [
            {
                "tool_id": item.capability_id,
                "required_params": list(item.required_params),
                "summary": item.summary,
            }
            for item in visible_results
        ]

    def _get_tool_info(
        tool_id: str,
        call_mode: str = "explore",
        response_detail: str = "",
    ) -> dict[str, object]:
        del call_mode, response_detail
        if tool_id in turn_state.denied_capability_ids:
            return {
                "tool_id": tool_id,
                "available": False,
                "reason": "tool is not available to this agent",
            }
        descriptor = _call_with_optional_meta(
            client.describe_capability,
            meta=turn_state.nested_call_meta(),
            capability_id=tool_id,
        )
        # Activate the tool so the model can call it on the next hop.
        # Unfreeze so _prepare_tools re-evaluates with the expanded set.
        turn_state.active_tool_names.add(descriptor.capability_id)
        turn_state.tools_frozen = False
        return {
            "tool_id": descriptor.capability_id,
            "available": True,
            "kind": descriptor.kind,
            "version": descriptor.version,
            "summary": descriptor.summary,
            "input_schema": descriptor.input_schema,
            "output_schema": descriptor.output_schema,
            "autonomy": descriptor.autonomy,
            "requires_approval": descriptor.requires_approval,
            "side_effects": list(descriptor.side_effects),
            "required_capabilities": list(descriptor.required_capabilities),
        }

    return [
        Tool.from_schema(
            _search_tools,
            name=_SEARCH_TOOLS_TOOL_NAME,
            description="Search available tools by concept and return matches.",
            json_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    **_AGENT_CONTEXT_PROPERTIES,
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        Tool.from_schema(
            _get_tool_info,
            name=_GET_TOOL_INFO_TOOL_NAME,
            description="Return the full schema and metadata for one tool by its ID.",
            json_schema={
                "type": "object",
                "properties": {
                    "tool_id": {"type": "string"},
                    **_AGENT_CONTEXT_PROPERTIES,
                },
                "required": ["tool_id"],
                "additionalProperties": False,
            },
        ),
    ]


def _build_prepare_tools(*, turn_state: _TurnState):
    """Return the supported PydanticAI prepare_tools hook for dynamic exposure."""

    async def _prepare_tools(
        _ctx: Any, tool_defs: list[ToolDefinition]
    ) -> list[ToolDefinition]:
        if not turn_state.tools_frozen:
            active = tuple(
                item for item in tool_defs if item.name in turn_state.active_tool_names
            )
            turn_state.frozen_tool_names = tuple(item.name for item in active)
            turn_state.tools_frozen = True
            return list(active)
        return [item for item in tool_defs if item.name in turn_state.frozen_tool_names]

    return _prepare_tools


def _sdk_config_from_settings(settings: ActorSettings) -> BrainSdkConfig:
    """Project actor settings into the SDK client configuration model."""
    return BrainSdkConfig(
        host=str(settings.core.host),
        port=int(settings.core.port),
        timeout_seconds=float(settings.core.timeout_seconds),
        source=str(settings.agent.source),
        principal=str(settings.agent.principal),
    )


def _derive_lms_request_timeout_seconds(core_runtime_settings) -> float:
    """Return one derived agent->core timeout for LMS chat requests only."""
    adapter_settings = resolve_llm_adapter_settings(core_runtime_settings)
    service_settings = core_runtime_settings.core.service.model_dump(mode="python")
    language_model = service_settings.get("language_model", {})
    standard = (
        language_model.get("standard", {}) if isinstance(language_model, dict) else {}
    )
    standard_provider = (
        str(standard.get("provider", "")).strip() if isinstance(standard, dict) else ""
    )

    def _profile_provider(name: str) -> str:
        profile = (
            language_model.get(name, {}) if isinstance(language_model, dict) else {}
        )
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
    return max_timeout_retry_budget_seconds(
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
            "brain agent tool-system hints unavailable",
            extra={"error_type": type(exc).__name__, "error_message": str(exc)},
        )
        return ()


def _create_runtime(
    *,
    client: BrainClient,
    settings: ActorSettings,
    core_settings: CoreSettings | None = None,
    lms_request_timeout_seconds: float | None = None,
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
    capabilities = client.describe_capabilities()
    always_on_capabilities = client.list_always_on_capabilities()
    tool_system_hints = render_system_tool_hints(_list_tool_system_hints(client))
    system_blocks = render_system_prompt_blocks(
        personality,
        operator_profile=operator_profile,
        system_tool_hints=tool_system_hints,
        system_prompt_append=system_prompt_append,
    )
    denied_capability_ids = frozenset(
        item.strip()
        for item in settings.agent.capability_discovery_deny_list
        if item.strip() != ""
    )
    turn_state = _TurnState(
        always_on_capability_ids=frozenset(
            item.capability_id
            for item in always_on_capabilities
            if item.capability_id not in denied_capability_ids
        ),
        denied_capability_ids=denied_capability_ids,
    )
    turn_state.reset_active_tools()
    model = _BrainSdkToolModel(
        client=client,
        turn_state=turn_state,
        timeout_seconds=lms_request_timeout_seconds,
        session_id=session.session_id,
        source=str(settings.agent.source),
        principal=str(settings.agent.principal),
        system_blocks=system_blocks,
        tool_requires_approval={
            **{item.capability_id: item.requires_approval for item in capabilities},
            _SEARCH_TOOLS_TOOL_NAME: False,
            _GET_TOOL_INFO_TOOL_NAME: False,
        },
    )
    capability_tools = _build_capability_tools(
        client=client,
        capabilities=capabilities,
        turn_state=turn_state,
    )
    runtime_tools = _build_runtime_tools(client=client, turn_state=turn_state)
    history_processor = _build_history_processor(
        client=client,
        timeout_seconds=lms_request_timeout_seconds,
        compress_threshold=settings.agent.tool_return_compress_threshold,
        max_chars=settings.agent.tool_return_max_chars,
        tier2_hop_threshold=settings.agent.tool_loop_tier2_hop_threshold,
    )
    agent = Agent(
        model,
        system_prompt="",
        retries=3,
        max_concurrency=1,
        tools=[*capability_tools, *runtime_tools],
        prepare_tools=_build_prepare_tools(turn_state=turn_state),
        history_processors=[history_processor],
        instrument=None,
    )
    return _AgentRuntime(
        client=client,
        session_id=session.session_id,
        turn_state=turn_state,
        model=model,
        agent=agent,
        lms_request_timeout_seconds=(
            0.0 if lms_request_timeout_seconds is None else lms_request_timeout_seconds
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
    instruction: SwitchboardOperatorInstruction,
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


def _estimate_token_count(text: str) -> int:
    """Estimate token count with the same simple heuristic MAS uses internally."""
    words = len([item for item in text.split() if item])
    if words <= 0:
        return 0
    estimated = words * 3
    return (estimated + 1) // 2


async def _compress_tool_return(
    *,
    client: BrainClient,
    tool_name: str,
    call_mode: str,
    response_detail: str,
    raw_content: str,
    max_chars: int,
    timeout_seconds: float | None = None,
) -> _CompressedToolReturn:
    """Call quick chat to compress one large tool return."""
    intent_hint = response_detail.strip() or f"tool call: {tool_name}"
    user_content = _render_prompt_template(
        _COMPRESS_USER_PROMPT_TEMPLATE,
        tool_name=tool_name,
        call_mode=call_mode,
        intent=intent_hint,
        raw_output=raw_content[:max_chars],
    )
    try:
        result = await asyncio.to_thread(
            client.lms_chat,
            system_prompt=_COMPRESS_SYSTEM_PROMPT,
            prompt=user_content,
            profile="quick",
            timeout_seconds=timeout_seconds,
        )
        compressed = result.text.strip()
        if compressed:
            return _CompressedToolReturn(
                content=compressed,
                model=result.model,
                provider=result.provider,
            )
    except Exception:
        _LOGGER.warning(
            "brain agent tool return compression failed; using truncation",
            extra={"tool_name": tool_name},
        )
    return _CompressedToolReturn(
        content=raw_content[:max_chars] + "\n[truncated]",
        model="",
        provider="",
    )


def _log_tool_return_audit(
    *,
    tool_name: str,
    tool_call_id: str,
    tool_args: dict[str, object],
    normalized: _NormalizedToolReturn,
) -> None:
    """Emit one structured audit record for a normalized tool return."""
    _LOGGER.debug(
        "brain agent normalized tool return",
        extra={
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "tool_input": tool_args,
            "raw_output": normalized.raw_content,
            "display_output": normalized.content,
            "normalization_kind": normalized.normalization_kind,
            "raw_char_count": normalized.raw_char_count,
            "final_char_count": normalized.final_char_count,
            "compressed_by_model": normalized.compressed_by_model,
            "compressed_by_provider": normalized.compressed_by_provider,
        },
    )


async def _normalize_tool_return(
    *,
    client: BrainClient,
    timeout_seconds: float | None = None,
    tool_name: str,
    tool_call_id: str,
    tool_args: dict[str, object],
    raw_content: str,
    compress_threshold: int,
    max_chars: int,
) -> _NormalizedToolReturn:
    """Normalize one tool return before it can re-enter the main model loop."""
    call_mode = str(tool_args.get("call_mode", "explore")).strip() or "explore"
    response_detail = str(tool_args.get("response_detail", ""))
    raw_char_count = len(raw_content)

    if raw_char_count <= compress_threshold:
        normalized = _NormalizedToolReturn(
            content=raw_content,
            normalization_kind="pass_through",
            raw_content=raw_content,
            raw_char_count=raw_char_count,
            final_char_count=raw_char_count,
        )
        _log_tool_return_audit(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
            normalized=normalized,
        )
        return normalized

    if call_mode == "decide":
        compressed = await _compress_tool_return(
            client=client,
            tool_name=tool_name,
            call_mode=call_mode,
            response_detail=response_detail,
            raw_content=raw_content,
            max_chars=max_chars,
            timeout_seconds=timeout_seconds,
        )
        normalized = _NormalizedToolReturn(
            content=compressed.content,
            normalization_kind="compress",
            raw_content=raw_content,
            raw_char_count=raw_char_count,
            final_char_count=len(compressed.content),
            compressed_by_model=compressed.model,
            compressed_by_provider=compressed.provider,
        )
        _log_tool_return_audit(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
            normalized=normalized,
        )
        return normalized

    if raw_char_count > max_chars:
        truncated = raw_content[:max_chars] + "\n[truncated]"
        normalized = _NormalizedToolReturn(
            content=truncated,
            normalization_kind="truncate",
            raw_content=raw_content,
            raw_char_count=raw_char_count,
            final_char_count=len(truncated),
        )
        _log_tool_return_audit(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
            normalized=normalized,
        )
        return normalized

    normalized = _NormalizedToolReturn(
        content=raw_content,
        normalization_kind="pass_through",
        raw_content=raw_content,
        raw_char_count=raw_char_count,
        final_char_count=raw_char_count,
    )
    _log_tool_return_audit(
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_args=tool_args,
        normalized=normalized,
    )
    return normalized


def _build_history_processor(
    *,
    client: BrainClient,
    timeout_seconds: float | None,
    compress_threshold: int,
    max_chars: int,
    tier2_hop_threshold: int,
):
    """Return a PydanticAI history_processor that manages caching and tool result size."""

    # Build an index of tool call args keyed by tool_call_id so the processor
    # can read call_mode and response_detail from the assistant's tool call args
    # when evaluating the corresponding tool return.
    def _tool_call_args_index(
        msgs: list[ModelRequest | ModelResponse],
    ) -> dict[str, dict[str, object]]:
        index: dict[str, dict[str, object]] = {}
        for msg in msgs:
            if not isinstance(msg, ModelResponse):
                continue
            for part in msg.parts:
                if not isinstance(part, ToolCallPart):
                    continue
                try:
                    args = (
                        part.args
                        if isinstance(part.args, dict)
                        else json.loads(part.args or "{}")
                    )
                    if isinstance(args, dict):
                        index[part.tool_call_id] = args
                except ValueError, TypeError:
                    pass
        return index

    async def _process_history(
        _ctx: RunContext[None],
        messages: list[ModelRequest | ModelResponse],
    ) -> list[ModelRequest | ModelResponse]:
        result: list[ModelRequest | ModelResponse] = []
        tier1_placed = False
        hop_count = sum(1 for m in messages if isinstance(m, ModelResponse))
        call_args_by_id = _tool_call_args_index(messages)

        for i, message in enumerate(messages):
            if not isinstance(message, ModelRequest):
                result.append(message)
                continue

            new_parts = []
            for part in message.parts:
                if isinstance(part, UserPromptPart) and not tier1_placed:
                    # Tier 1: stable cache point after system + MAS historical snapshot.
                    # Byte-stable across all intra-turn hops as long as tool array
                    # does not change.
                    if _content_has_cache_point(part.content):
                        new_parts.append(part)
                    else:
                        if isinstance(part.content, str):
                            new_content: list[UserContent] = [part.content]
                        else:
                            new_content = list(part.content)
                        new_content.append(CachePoint())
                        new_parts.append(UserPromptPart(content=new_content))
                    tier1_placed = True
                    continue

                if isinstance(part, ToolReturnPart):
                    raw = _stringify_content(part.content)
                    call_args = call_args_by_id.get(part.tool_call_id, {})
                    normalized = await _normalize_tool_return(
                        client=client,
                        timeout_seconds=timeout_seconds,
                        tool_name=part.tool_name,
                        tool_call_id=part.tool_call_id,
                        tool_args=call_args,
                        raw_content=raw,
                        compress_threshold=compress_threshold,
                        max_chars=max_chars,
                    )
                    new_parts.append(
                        ToolReturnPart(
                            tool_name=part.tool_name,
                            content=normalized.content,
                            tool_call_id=part.tool_call_id,
                        )
                    )
                    continue

                new_parts.append(part)

            # Tier 2: dynamic cache point after accumulated tool exchanges when the
            # turn has run deep enough to warrant it. Placed after the last tool
            # return in the final request, covering all prior exchanges at 10% read
            # cost on subsequent hops.
            if (
                hop_count >= tier2_hop_threshold
                and i == len(messages) - 1
                and any(isinstance(p, ToolReturnPart) for p in new_parts)
            ):
                tool_returns = [
                    part for part in new_parts if isinstance(part, ToolReturnPart)
                ]
                last_tool_idx = max(
                    j for j, p in enumerate(new_parts) if isinstance(p, ToolReturnPart)
                )
                candidate_parts = list(new_parts)
                candidate_parts.insert(
                    last_tool_idx + 1,
                    UserPromptPart(content=[CachePoint()]),
                )
                score = _rolling_cachepoint_score(
                    tool_returns=tool_returns,
                    call_args_by_id=call_args_by_id,
                    hop_count=hop_count,
                    candidate_messages=[
                        *result,
                        ModelRequest(parts=new_parts),
                    ],
                )
                if score > 0.0:
                    new_parts = candidate_parts

            result.append(ModelRequest(parts=new_parts))

        return result

    return _process_history


def _instruction_context_message(instruction: SwitchboardOperatorInstruction) -> str:
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


def _is_retryable_lms_throttle(exc: BrainDependencyError) -> bool:
    """Return True when one LMS dependency failure represents provider throttling."""
    if exc.operation not in {"lms.chat", "lms.chat_with_tools"}:
        return False
    if not any(detail.retryable for detail in exc.details):
        return False
    message = str(exc).lower()
    throttle_tokens = ("rate limit", "rate_limit", "throttle", "too many requests")
    return any(token in message for token in throttle_tokens)


def _is_retryable_lms_timeout(exc: BrainDependencyError) -> bool:
    """Return True when one LMS dependency failure represents timeout exhaustion."""
    if exc.operation not in {"lms.chat", "lms.chat_with_tools"}:
        return False
    if not any(detail.retryable for detail in exc.details):
        return False
    message = str(exc).lower()
    timeout_tokens = ("timed out", "timeout", "readtimeout")
    return any(token in message for token in timeout_tokens)


def _is_retryable_lms_transport_timeout(exc: BrainTransportError) -> bool:
    """Return True when one LMS transport failure represents timeout exhaustion."""
    if exc.operation not in {"lms.chat", "lms.chat_with_tools"}:
        return False
    if not exc.retryable:
        return False
    message = str(exc).lower()
    timeout_tokens = ("timed out", "timeout", "readtimeout")
    return any(token in message for token in timeout_tokens)


def _is_retryable_lms_transport_failure(exc: BrainTransportError) -> bool:
    """Return True when one LMS transport failure merits another whole-turn try."""
    if exc.operation not in {"lms.chat", "lms.chat_with_tools"}:
        return False
    return exc.retryable or exc.status_code >= 500 or exc.status_code == 429


def _is_retryable_lms_internal_failure(exc: BrainInternalError) -> bool:
    """Return True when one LMS internal failure is marked as recoverable."""
    if exc.operation not in {"lms.chat", "lms.chat_with_tools"}:
        return False
    return any(detail.retryable for detail in exc.details)


def _should_retry_lms_failure(exc: BrainSdkError) -> bool:
    """Return True when one LMS failure should trigger local recovery attempts."""
    if isinstance(exc, BrainDependencyError):
        return any(detail.retryable for detail in exc.details)
    if isinstance(exc, BrainTransportError):
        return _is_retryable_lms_transport_failure(exc)
    if isinstance(exc, BrainInternalError):
        return _is_retryable_lms_internal_failure(exc)
    return False


def _should_notify_operator_of_lms_recovery(exc: BrainSdkError) -> bool:
    """Return True when one LMS failure warrants a visible in-progress notice."""
    return isinstance(exc, (BrainDependencyError, BrainTransportError)) and (
        _should_retry_lms_failure(exc)
    )


def _lms_recovery_profile_sequence(initial_profile: str) -> tuple[str, ...]:
    """Return the ordered profile fallback sequence for one turn."""
    if initial_profile == "quick":
        candidates = ("quick", "standard", "deep")
    elif initial_profile == "deep":
        candidates = ("deep", "standard", "quick")
    else:
        candidates = ("standard", "quick", "deep")
    return tuple(dict.fromkeys(candidates))


async def _notify_operator_of_lms_recovery(
    *,
    client: BrainClient,
    turn_state: _TurnState,
    session_id: str,
    message: str,
    reasoning_level: str,
) -> None:
    """Send one best-effort operator-facing notice that LMS recovery is underway."""
    payload: dict[str, object] = {
        "actor": "operator",
        "channel": turn_state.channel,
        "message": message,
        "conversational_memory": {
            "session_id": session_id,
            "model": "brain-sdk-lms",
            "provider": "brain-sdk",
            "token_count": _estimate_token_count(message),
            "reasoning_level": reasoning_level,
        },
    }
    try:
        await asyncio.to_thread(
            _call_with_optional_meta,
            client.invoke_capability,
            meta=turn_state.nested_call_meta(),
            capability_id="attention-notify",
            input_payload=payload,
            actor="operator",
            channel=turn_state.channel,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "brain agent lms recovery notify failed",
            extra={
                "capability_id": "attention-notify",
                "channel": turn_state.channel,
                "actor": "operator",
            },
        )


def _is_lms_operation(operation: str) -> bool:
    """Return True when one SDK operation is an LMS generation call."""
    return operation in {"lms.chat", "lms.chat_with_tools"}


def _classify_lms_failure_response(exc: BrainSdkError) -> str | None:
    """Return one fallback operator response for handled LMS failures."""
    operation = getattr(exc, "operation", "")
    if not isinstance(operation, str) or not _is_lms_operation(operation):
        return None
    if isinstance(exc, BrainDependencyError):
        if _is_retryable_lms_throttle(exc):
            return _LMS_THROTTLE_RESPONSE
        if _is_retryable_lms_timeout(exc):
            return _LMS_TIMEOUT_RESPONSE
        return _LMS_GENERIC_ERROR_RESPONSE
    if isinstance(exc, BrainTransportError):
        if _is_retryable_lms_transport_timeout(exc):
            return _LMS_TIMEOUT_RESPONSE
        return _LMS_GENERIC_ERROR_RESPONSE
    if isinstance(exc, BrainDomainError):
        return _LMS_GENERIC_ERROR_RESPONSE
    return None


async def _process_instruction(
    *,
    runtime: _AgentRuntime,
    instruction: SwitchboardOperatorInstruction,
) -> str:
    """Handle one inbound operator instruction end-to-end."""
    runtime.turn_state.prune_pending_invocations()
    runtime.turn_state.begin_turn_trace()
    with _agent_turn_observation(runtime=runtime, instruction=instruction) as turn_span:
        _set_current_span_attributes(
            {
                "brain.operation": "agent.turn",
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
                _call_with_optional_meta,
                assemble_context,
                meta=runtime.turn_state.nested_call_meta(),
                session_id=runtime.session_id,
                message=_instruction_context_message(instruction),
                instruction=instruction,
            )
        else:
            _inbound_turn = await asyncio.to_thread(
                _call_with_optional_meta,
                runtime.client.memory_record_inbound_turn,
                meta=runtime.turn_state.nested_call_meta(),
                session_id=runtime.session_id,
                message=_instruction_context_message(instruction),
                instruction=instruction,
            )
            context = await asyncio.to_thread(
                _call_with_optional_meta,
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
            _LOGGER.warning(
                "brain agent environment context capability failed",
                extra={
                    "capability_id": diagnostic.capability_id,
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
            fallback_response = _classify_lms_failure_response(exc)
            if fallback_response is None:
                raise
            _LOGGER.warning(
                "brain agent lms request failed; returning fallback response",
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
    instruction: SwitchboardOperatorInstruction,
    response_text: str,
    model: str,
    provider: str,
    reasoning_level: str,
) -> bool:
    """Deliver one finalized response via Attention Router notify capability."""
    payload: dict[str, object] = {
        "actor": "operator",
        "channel": instruction.source,
        "message": response_text,
        "conversational_memory": {
            "session_id": runtime.session_id,
            "model": model,
            "provider": provider,
            "token_count": _estimate_token_count(response_text),
            "reasoning_level": reasoning_level,
        },
    }
    try:
        await asyncio.to_thread(
            _call_with_optional_meta,
            runtime.client.invoke_capability,
            meta=runtime.turn_state.nested_call_meta(),
            capability_id="attention-notify",
            input_payload=payload,
            actor="operator",
            channel=instruction.source,
        )
        return True
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "brain agent outbound notify failed",
            extra={
                "capability_id": "attention-notify",
                "channel": instruction.source,
                "actor": "operator",
            },
        )
        return False


async def _run_main() -> None:
    """Run the long-lived Brain Agent process inside one event loop."""
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
            lms_request_timeout_seconds=_derive_lms_request_timeout_seconds(
                core_runtime_settings
            ),
        )
        _LOGGER.info(
            "brain agent started",
            extra={
                "core_host": settings.core.host,
                "core_port": settings.core.port,
                "timeout_seconds": settings.core.timeout_seconds,
                "lms_request_timeout_seconds": runtime.lms_request_timeout_seconds,
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
                    runtime.client.switchboard_poll_operator_instruction,
                    wait_timeout_seconds=wait_timeout_seconds,
                )
                _write_heartbeat(path=heartbeat_path)
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
                _write_heartbeat(path=heartbeat_path)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("brain agent turn failed")
                _write_heartbeat(path=heartbeat_path)
                await asyncio.sleep(1.0)
    finally:
        client.close()
        _LOGGER.info("brain agent stopped")


def main() -> None:
    """Run the long-lived Brain Agent process."""
    asyncio.run(_run_main())


if __name__ == "__main__":
    main()
