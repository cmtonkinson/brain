"""Runtime entrypoint for the long-lived Brain Assistant container."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from pydantic_ai.tools import ToolDefinition

from lib.agent import (
    is_retryable_language_throttle,
    is_retryable_language_timeout,
    is_retryable_language_transport_timeout,
)
from lib.agent.content_parts import (
    content_has_cache_point,
    stringify_content,
    to_content_parts,
)
from lib.agent.inference_request import (
    classify_tool_result_status,
    is_not_found_tool_result,
    tool_args_json,
)
from lib.agent.tool_model import AgentToolModel, call_with_optional_meta
from lib.shared.observability import (
    set_current_span_attributes,
    set_span_attributes,
)
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
    OpDescriptor,
    MemoryContextBlock,
    MetaOverrides,
    RelayOperatorInstruction,
    ToolSystemHint,
    render_system_prompt_blocks,
    render_system_tool_hints,
)
from lib.sdk.errors import BrainSdkError
from lib.shared.config import (
    ActorSettings,
    CoreRuntimeSettings,
    CoreSettings,
    component_settings_for,
    load_actor_settings,
    load_core_runtime_settings,
)
from lib.shared.ids import generate_ulid_str
from lib.shared.language_model import (
    CachePointContentPart,
    ConversationSummaryContentPart,
    DialogueTurnContentPart,
    EnvironmentContextContentPart,
    FocusContentPart,
    InferenceEnvironmentContext,
    InferenceSystemBlock,
    OperatorMessageContentPart,
    ReferenceSnippetContentPart,
)
from lib.sdk.environment import assemble_environment_context
from lib.shared.observability import (
    bootstrap_observability,
    is_observability_enabled,
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
_LMS_TIMEOUT_MARGIN_SECONDS = 2.0
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
_HEARTBEAT_FILE_ENV = "BRAIN_ASSISTANT_HEARTBEAT_FILE"
_HEARTBEAT_PATH = Path("/run/brain/assistant-heartbeat")
_PROMPT_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
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
# Anthropic cache pricing factors: reads cost ~90% less than uncached;
# write premium is ~25% of the uncached token cost.
# PydanticAI retries on invalid tool call responses.
_AGENT_TOOL_CALL_RETRIES = 3
# Tool calls execute sequentially; parallelism is managed per-hop via prepare_tools.
_AGENT_MAX_CONCURRENCY = 1
# Brief pause after a turn exception before resuming the poll loop.
_TURN_FAILURE_BACKOFF_SECONDS = 1.0
_RELAY_NOTIFY_OP_ID = "relay-notify"
_ANTHROPIC_CACHE_READ_SAVINGS_FACTOR = 0.90
_ANTHROPIC_CACHE_WRITE_PREMIUM_FACTOR = 0.25


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


@dataclass(frozen=True, slots=True)
class _PendingInvocation:
    """Short-lived record for one approval-gated op attempt."""

    proposal_token: str
    op_id: str
    input_payload: dict[str, object]
    actor: str
    channel: str
    approval: str
    reason_codes: tuple[str, ...]
    created_at: datetime
    expires_at: datetime | None = None


@dataclass(slots=True)
class _TurnState:
    """Mutable turn-local metadata shared by op tool wrappers."""

    actor: str = "operator"
    channel: str = ""
    trace_id: str = ""
    conversation_episode_id: str = ""
    root_envelope_id: str = ""
    current_model_envelope_id: str = ""
    always_on_op_ids: frozenset[str] = frozenset()
    denied_op_ids: frozenset[str] = frozenset()
    active_tool_names: set[str] = field(default_factory=set)
    frozen_tool_names: tuple[str, ...] = ()
    tools_frozen: bool = False
    pending_invocations: dict[str, _PendingInvocation] = field(default_factory=dict)
    reply_to_proposal_token: str = ""
    reaction_to_proposal_token: str = ""
    language_recovery_notice_sent: bool = False

    def reset_active_tools(self) -> None:
        """Reset the active tool set to the always-on Execution tools plus runtime tools.

        Op tools that were dynamically promoted via ``get_tool_info`` during
        the prior turn are carried forward so multi-turn flows (e.g. an op
        invocation that requires operator approval over a separate message)
        do not have to re-discover the same op every turn. Denied ops are
        always evicted, regardless of prior promotion.
        """
        carry_forward = {
            name
            for name in self.active_tool_names
            if name not in (_SEARCH_TOOLS_TOOL_NAME, _GET_TOOL_INFO_TOOL_NAME)
            and name not in self.denied_op_ids
        }
        self.tools_frozen = False
        self.frozen_tool_names = ()
        self.active_tool_names = {
            *(
                op_id
                for op_id in self.always_on_op_ids
                if op_id not in self.denied_op_ids
            ),
            *carry_forward,
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
        op_id: str,
        input_payload: dict[str, object],
        approval: str,
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
            op_id=op_id,
            input_payload=dict(input_payload),
            actor=self.actor,
            channel=self.channel,
            approval=approval,
            reason_codes=reason_codes,
            created_at=effective_now,
            expires_at=expires_at,
        )
        self.prune_pending_invocations(now=effective_now)

    def proposal_token_for_retry(
        self,
        *,
        op_id: str,
        input_payload: dict[str, object],
    ) -> tuple[str, str]:
        """Return matched reply/reaction proposal correlators for one safe retry."""
        reply_token = self.reply_to_proposal_token.strip()
        reaction_token = self.reaction_to_proposal_token.strip()
        matched_reply = self._matching_pending_token(
            proposal_token=reply_token,
            op_id=op_id,
            input_payload=input_payload,
        )
        matched_reaction = self._matching_pending_token(
            proposal_token=reaction_token,
            op_id=op_id,
            input_payload=input_payload,
        )
        return matched_reply, matched_reaction

    def _matching_pending_token(
        self,
        *,
        proposal_token: str,
        op_id: str,
        input_payload: dict[str, object],
    ) -> str:
        """Return one proposal token only when it matches a stored blocked invocation."""
        token = proposal_token.strip()
        if token == "":
            return ""
        pending = self.pending_invocations.get(token)
        if pending is None:
            return ""
        if pending.op_id != op_id:
            return ""
        if pending.input_payload != input_payload:
            return ""
        return token

    def begin_turn_trace(self) -> None:
        """Start one fresh trace context for the current operator turn."""
        self.trace_id = generate_ulid_str()
        self.root_envelope_id = generate_ulid_str()
        self.current_model_envelope_id = ""
        self.language_recovery_notice_sent = False

    def next_model_meta(self) -> MetaOverrides:
        """Allocate metadata for one Language request within the active turn trace."""
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
    model: AgentToolModel
    agent: Agent[None, str]
    language_request_timeout_seconds: float
    preferred_timezone: str = "UTC"
    system_blocks: tuple[InferenceSystemBlock, ...] = ()
    environment_context_entries: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class _CompressedToolReturn:
    """Result of one secondary Language compression call for a tool return."""

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
                    for content_part in to_content_parts(part.content):
                        if isinstance(content_part, CachePointContentPart):
                            reset_segments()
                            continue
                        append_text(stringify_content(content_part))
                    continue
                if isinstance(part, ToolReturnPart):
                    append_text(part.tool_name)
                    append_text(stringify_content(part.content))
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
                append_text(tool_args_json(part.args))
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
        status = classify_tool_result_status(part.content)
        if call_mode == "explore":
            explore_count += 1.0
        if part.tool_name in _DISCOVERY_TOOL_NAMES:
            discovery_count += 1.0
        if status in {"error", "empty"}:
            failure_count += 1.0
        if is_not_found_tool_result(part.content):
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
    return float(delta_tokens) * (
        (_ANTHROPIC_CACHE_READ_SAVINGS_FACTOR * expected_reuses)
        - _ANTHROPIC_CACHE_WRITE_PREMIUM_FACTOR
    )


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


def _build_op_tools(
    *,
    client: BrainClient,
    ops: tuple[OpDescriptor, ...],
    turn_state: _TurnState,
) -> list[Tool[None]]:
    """Create one PydanticAI tool wrapper per active Op."""
    tools: list[Tool[None]] = []
    for descriptor in ops:
        summary = descriptor.summary.strip()
        description = summary
        input_schema = (
            {"type": "object", "properties": {}, "additionalProperties": False}
            if descriptor.input_schema is None
            else dict(descriptor.input_schema)
        )

        def _invoke(
            _op_id: str = descriptor.op_id,
            _approval: str = descriptor.approval,
            **input_payload: object,
        ) -> object:
            # Strip agent-only context properties before forwarding to the op.
            op_payload = {
                k: v
                for k, v in input_payload.items()
                if k not in _AGENT_CONTEXT_PROPERTIES
            }
            reply_token, reaction_token = turn_state.proposal_token_for_retry(
                op_id=_op_id,
                input_payload=op_payload,
            )
            try:
                result = call_with_optional_meta(
                    client.invoke_op,
                    meta=turn_state.nested_call_meta(),
                    op_id=_op_id,
                    input_payload=op_payload,
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
                        op_id=_op_id,
                        input_payload=op_payload,
                        approval=_approval,
                        reason_codes=tuple(reason_codes),
                        expires_at=expires_at,
                    )
                return {
                    "error": "policy_denied",
                    "message": str(exc),
                    "op_id": _op_id,
                    "approval": _approval,
                    "proposal_token": proposal_token,
                    "proposal_expires_at": (
                        "" if expires_at is None else expires_at.isoformat()
                    ),
                    "reason_codes": reason_codes,
                }
            except BrainValidationError as exc:
                return _op_error_payload(
                    error="validation_error",
                    op_id=_op_id,
                    exc=exc,
                )
            except BrainConflictError as exc:
                return _op_error_payload(
                    error="conflict_error",
                    op_id=_op_id,
                    exc=exc,
                )
            except BrainNotFoundError as exc:
                return _op_error_payload(
                    error="not_found",
                    op_id=_op_id,
                    exc=exc,
                )
            except BrainDependencyError as exc:
                return _op_error_payload(
                    error="dependency_error",
                    op_id=_op_id,
                    exc=exc,
                )
            except BrainInternalError as exc:
                _LOGGER.error(
                    "brain assistant op tool internal error",
                    extra={"op_id": _op_id},
                )
                return _op_error_payload(
                    error="internal_error",
                    op_id=_op_id,
                    exc=exc,
                )
            except BrainDomainError as exc:
                return _op_error_payload(
                    error="domain_error",
                    op_id=_op_id,
                    exc=exc,
                )
            return result.output

        tools.append(
            Tool.from_schema(
                _invoke,
                name=descriptor.op_id,
                description=description,
                json_schema=input_schema,
            )
        )
    return tools


def _op_error_payload(
    *,
    error: str,
    op_id: str,
    exc: BrainDomainError,
) -> dict[str, object]:
    """Return one stable tool error payload for SDK domain failures."""
    return {
        "error": error,
        "message": str(exc),
        "op_id": op_id,
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
    """Create hardcoded runtime discovery tools for dynamic op exposure."""

    def _search_tools(
        query: str,
        limit: int | None = None,
        call_mode: str = "explore",  # noqa: ARG001 — part of tool schema, not used here
        response_detail: str = "",  # noqa: ARG001 — part of tool schema, not used here
    ) -> list[dict[str, object]]:
        results = call_with_optional_meta(
            client.search_ops,
            meta=turn_state.nested_call_meta(),
            query=query,
            limit=limit,
        )
        visible_results = [
            item for item in results if item.op_id not in turn_state.denied_op_ids
        ]
        return [
            {
                "tool_id": item.op_id,
                "required_params": list(item.required_params),
                "summary": item.summary,
            }
            for item in visible_results
        ]

    def _get_tool_info(
        tool_id: str,
        call_mode: str = "explore",  # noqa: ARG001 — part of tool schema, not used here
        response_detail: str = "",  # noqa: ARG001 — part of tool schema, not used here
    ) -> dict[str, object]:
        if tool_id in turn_state.denied_op_ids:
            return {
                "tool_id": tool_id,
                "available": False,
                "reason": "tool is not available to this agent",
            }
        descriptor = call_with_optional_meta(
            client.describe_op,
            meta=turn_state.nested_call_meta(),
            op_id=tool_id,
        )
        # Activate the tool so the model can call it on the next hop.
        # Unfreeze so _prepare_tools re-evaluates with the expanded set.
        turn_state.active_tool_names.add(descriptor.op_id)
        turn_state.tools_frozen = False
        return {
            "tool_id": descriptor.op_id,
            "available": True,
            "kind": descriptor.kind,
            "version": descriptor.version,
            "summary": descriptor.summary,
            "input_schema": descriptor.input_schema,
            "output_schema": descriptor.output_schema,
            "effect": descriptor.effect,
            "approval": descriptor.approval,
            "required_ops": list(descriptor.required_ops),
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
    )
    op_tools = _build_op_tools(
        client=client,
        ops=ops,
        turn_state=turn_state,
    )
    runtime_tools = _build_runtime_tools(client=client, turn_state=turn_state)
    history_processor = _build_history_processor(
        client=client,
        timeout_seconds=language_request_timeout_seconds,
        compress_threshold=settings.agent.tool_return_compress_threshold,
        max_chars=settings.agent.tool_return_max_chars,
        tier2_hop_threshold=settings.agent.tool_loop_tier2_hop_threshold,
    )
    agent = Agent(
        model,
        system_prompt="",
        retries=_AGENT_TOOL_CALL_RETRIES,
        max_concurrency=_AGENT_MAX_CONCURRENCY,
        tools=[*op_tools, *runtime_tools],
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


def _estimate_token_count(text: str) -> int:
    """Estimate token count with the same simple heuristic Recall uses internally."""
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
            client.language_chat,
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
            "brain assistant tool return compression failed; using truncation",
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
        "brain assistant normalized tool return",
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
                    # Tier 1: stable cache point after system + Recall historical snapshot.
                    # Byte-stable across all intra-turn hops as long as tool array
                    # does not change.
                    if content_has_cache_point(part.content):
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
                    raw = stringify_content(part.content)
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
            "token_count": _estimate_token_count(message),
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
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "brain assistant lms recovery notify failed",
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
            "token_count": _estimate_token_count(response_text),
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
