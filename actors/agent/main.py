"""Runtime entrypoint for the long-lived Brain Agent container."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import inspect
import json
import logging
import os
from pathlib import Path
import re
import signal
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.messages import (
    CachePoint,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
    UserContent,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.tools import ToolDefinition

from packages.brain_sdk import (
    BrainClient,
    BrainConflictError,
    BrainDependencyError,
    BrainDomainError,
    BrainInternalError,
    BrainNotFoundError,
    BrainPolicyError,
    BrainTransportError,
    BrainSdkConfig,
    BrainValidationError,
    CapabilityDescriptor,
    LmsChatMessage,
    LmsChatToolCall,
    LmsChatToolDefinition,
    LmsToolChatResult,
    MetaOverrides,
    MemoryContextBlock,
    SwitchboardOperatorInstruction,
)
from packages.brain_shared.config import (
    ActorSettings,
    CoreSettings,
    load_actor_settings,
    load_core_runtime_settings,
)
from packages.brain_shared.ids import generate_ulid_str
from resources.adapters.litellm.config import (
    max_timeout_retry_budget_seconds,
    resolve_litellm_adapter_settings,
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
_LMS_TIMEOUT_MARGIN_SECONDS = 2.0
_AGENT_DIR = Path(__file__).resolve().parent
_PROMPTS_DIR = _AGENT_DIR / "prompts"
_COMPRESS_SYSTEM_PROMPT_PATH = _PROMPTS_DIR / "compress-tool-return.txt"
_COMPRESS_USER_PROMPT_TEMPLATE_PATH = (
    _PROMPTS_DIR / "compress-tool-return-user-template.txt"
)
_AGENT_CONTEXT_PROPERTIES_PATH = _AGENT_DIR / "tool-context-properties.json"
_DISCOVER_CAPABILITIES_TOOL_NAME = "discover_capabilities"
_DESCRIBE_CAPABILITY_TOOL_NAME = "describe_capability"
_MAX_PENDING_INVOCATIONS = 128
_HEARTBEAT_FILE_ENV = "BRAIN_AGENT_HEARTBEAT_FILE"
_HEARTBEAT_PATH = Path("/run/brain/agent-heartbeat")
_PROMPT_TEMPLATE_VAR_RE = re.compile(r"\{\{([a-z_][a-z0-9_]*)\}\}")


def _load_prompt_file(path: Path) -> str:
    """Load one prompt text file from disk and strip outer whitespace."""
    return path.read_text(encoding="utf-8").strip()


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
    """Render one simple prompt template using explicit string replacement."""
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    unresolved = _PROMPT_TEMPLATE_VAR_RE.findall(rendered)
    if unresolved:
        raise ValueError(
            f"unresolved prompt template placeholders: {', '.join(sorted(unresolved))}"
        )
    return rendered


def _call_with_optional_meta(func, /, *, meta: MetaOverrides | None, **kwargs: Any):
    """Call one SDK-style method, omitting ``meta`` for legacy fake clients."""
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "meta" in parameters:
        return func(meta=meta, **kwargs)
    return func(**kwargs)


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
    root_envelope_id: str = ""
    current_model_envelope_id: str = ""
    always_on_capability_ids: frozenset[str] = frozenset()
    denied_capability_ids: frozenset[str] = frozenset()
    active_tool_names: set[str] = field(default_factory=set)
    tools_frozen: bool = False
    pending_invocations: dict[str, _PendingInvocation] = field(default_factory=dict)
    reply_to_proposal_token: str = ""
    reaction_to_proposal_token: str = ""

    def reset_active_tools(self) -> None:
        """Reset the active tool set to the always-on CES tools plus runtime tools."""
        self.tools_frozen = False
        self.active_tool_names = {
            *(
                capability_id
                for capability_id in self.always_on_capability_ids
                if capability_id not in self.denied_capability_ids
            ),
            _DISCOVER_CAPABILITIES_TOOL_NAME,
            _DESCRIBE_CAPABILITY_TOOL_NAME,
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
    from packages.brain_shared.logging import configure_logging

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
    ) -> None:
        super().__init__(profile=ModelProfile(supports_tools=True))
        self._client = client
        self._turn_state = _TurnState() if turn_state is None else turn_state
        self._profile_name = profile_name
        self._timeout_seconds = timeout_seconds
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
            _call_with_optional_meta,
            self._client.lms_chat_with_tools,
            meta=self._turn_state.next_model_meta(),
            messages=tuple(_to_sdk_messages(messages)),
            tools=tuple(
                _to_sdk_tool_definition(item) for item in prepared_params.function_tools
            ),
            allow_text_output=prepared_params.allow_text_output,
            profile=self._profile_name,
            timeout_seconds=self._timeout_seconds,
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
    if isinstance(value, list | tuple):
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


def _content_has_cache_point(value: object) -> bool:
    """Return whether one structured user-content payload already includes cache."""
    if isinstance(value, CachePoint):
        return True
    if isinstance(value, list | tuple):
        return any(_content_has_cache_point(item) for item in value)
    return False


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
                content = _stringify_content(part.content)
                if content == "":
                    continue
                result.append(
                    LmsChatMessage(
                        role="user",
                        content=content,
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


def _to_sdk_tool_definition(value: ToolDefinition) -> LmsChatToolDefinition:
    """Convert one PydanticAI tool definition into an SDK LMS tool definition."""
    return LmsChatToolDefinition(
        name=value.name,
        parameters_json_schema=_tool_schema_with_agent_context(
            dict(value.parameters_json_schema)
        ),
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

    def _discover_capabilities(
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
        for item in visible_results:
            turn_state.active_tool_names.add(item.capability_id)
        return [
            {
                "capability_id": item.capability_id,
                "required_params": list(item.required_params),
                "summary": item.summary,
            }
            for item in visible_results
        ]

    def _describe_capability(
        capability_id: str,
        call_mode: str = "explore",
        response_detail: str = "",
    ) -> dict[str, object]:
        del call_mode, response_detail
        if capability_id in turn_state.denied_capability_ids:
            return {
                "capability_id": capability_id,
                "available": False,
                "reason": "capability is denied for this agent",
            }
        descriptor = _call_with_optional_meta(
            client.describe_capability,
            meta=turn_state.nested_call_meta(),
            capability_id=capability_id,
        )
        turn_state.active_tool_names.add(descriptor.capability_id)
        return {
            "capability_id": descriptor.capability_id,
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
            _discover_capabilities,
            name=_DISCOVER_CAPABILITIES_TOOL_NAME,
            description=(
                "Search the capability catalog semantically and activate matching "
                "capability tools for the next model step."
            ),
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
            _describe_capability,
            name=_DESCRIBE_CAPABILITY_TOOL_NAME,
            description=(
                "Return the full descriptor for one capability id and activate "
                "that tool for the next model step."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "capability_id": {"type": "string"},
                    **_AGENT_CONTEXT_PROPERTIES,
                },
                "required": ["capability_id"],
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
            # First LLM call of the turn: build the active set normally and freeze it.
            # Any capability names added by discovery tools between hops are ignored
            # until the next turn — this keeps the tools array byte-stable for caching.
            active = [
                item for item in tool_defs if item.name in turn_state.active_tool_names
            ]
            turn_state.active_tool_names = {t.name for t in active}
            turn_state.tools_frozen = True
            return active
        # Subsequent hops: return exactly the frozen set, ignoring any names added
        # by discovery tool execution since the first hop.
        return [item for item in tool_defs if item.name in turn_state.active_tool_names]

    return _prepare_tools


def _brain_sdk_config_from_settings(settings: ActorSettings) -> BrainSdkConfig:
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
    adapter_settings = resolve_litellm_adapter_settings(core_runtime_settings)
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


def _create_runtime(
    *,
    client: BrainClient,
    settings: ActorSettings,
    core_settings: CoreSettings | None = None,
    lms_request_timeout_seconds: float | None = None,
) -> _AgentRuntime:
    """Create one fully wired agent runtime from the published Core surface."""
    effective_core_settings = CoreSettings() if core_settings is None else core_settings
    session = client.memory_start_session(
        personality=effective_core_settings.profile.personality
    )
    capabilities = client.describe_capabilities()
    always_on_capabilities = client.list_always_on_capabilities()
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
        system_prompt=session.system_prompt,
        retries=3,
        max_concurrency=1,
        tools=[*capability_tools, *runtime_tools],
        prepare_tools=_build_prepare_tools(turn_state=turn_state),
        history_processors=[history_processor],
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
    )


def _long_poll_timeout_seconds(*, sdk_timeout_seconds: float) -> float:
    """Choose one bounded long-poll timeout that stays under the HTTP timeout."""
    return max(_MIN_LONG_POLL_SECONDS, sdk_timeout_seconds - _LONG_POLL_BUFFER_SECONDS)


def _format_user_prompt(
    *,
    instruction: SwitchboardOperatorInstruction,
    context: MemoryContextBlock,
) -> list[UserContent]:
    """Render one full prompt with stable context before the current instruction."""
    dialogue_lines = [f"- {turn.role}: {turn.content}" for turn in context.dialogue]
    snippet_lines = [f"- {snippet}" for snippet in context.reference_snippets]
    return [
        "MAS Context",
        "profile:",
        f"operator_name: {context.profile.operator_name}",
        f"brain_name: {context.profile.brain_name}",
        f"brain_verbosity: {context.profile.brain_verbosity}",
        "focus:",
        f"focus: {'' if context.focus is None else context.focus}",
        "historical_snapshot:",
        *(dialogue_lines or ["- (none)"]),
        CachePoint(),
        "reference_snippets:",
        *(snippet_lines or ["- (none)"]),
        "Current Instruction:",
        f"channel: {instruction.source}",
        f"sender: {instruction.sender_e164}",
        f"message: {instruction.message_text}",
        f"approval_intent: {'' if instruction.approval_intent is None else instruction.approval_intent}",
        f"reaction_emoji: {'' if instruction.reaction_emoji is None else instruction.reaction_emoji}",
        f"quote_target_timestamp_ms: {'' if instruction.quote_target_timestamp_ms is None else instruction.quote_target_timestamp_ms}",
        f"reaction_target_timestamp_ms: {'' if instruction.reaction_target_timestamp_ms is None else instruction.reaction_target_timestamp_ms}",
        f"reply_to_proposal_token: {'' if instruction.reply_to_proposal_token is None else instruction.reply_to_proposal_token}",
        f"reaction_to_proposal_token: {'' if instruction.reaction_to_proposal_token is None else instruction.reaction_to_proposal_token}",
    ]


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
    """Call Haiku to compress one large tool return to relevant content only.

    Uses lms_chat_with_tools (no tools, text-only) so the call is captured in
    the audit table alongside all other LMS calls for observability.
    """
    intent_hint = response_detail.strip() or f"tool call: {tool_name}"
    user_content = _render_prompt_template(
        _COMPRESS_USER_PROMPT_TEMPLATE,
        tool_name=tool_name,
        call_mode=call_mode,
        intent=intent_hint,
        raw_output=raw_content[:max_chars],
    )
    messages = (
        LmsChatMessage(role="system", content=_COMPRESS_SYSTEM_PROMPT),
        LmsChatMessage(role="user", content=user_content),
    )
    try:
        result = await asyncio.to_thread(
            client.lms_chat_with_tools,
            messages=messages,
            tools=(),
            allow_text_output=True,
            profile="quick",
            timeout_seconds=timeout_seconds,
        )
        compressed = (result.text or "").strip()
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
                except (ValueError, TypeError):
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
                last_tool_idx = max(
                    j for j, p in enumerate(new_parts) if isinstance(p, ToolReturnPart)
                )
                new_parts.insert(
                    last_tool_idx + 1, UserPromptPart(content=[CachePoint()])
                )

            result.append(ModelRequest(parts=new_parts))

        return result

    return _process_history


def _instruction_context_message(instruction: SwitchboardOperatorInstruction) -> str:
    """Return the best available text surrogate for one inbound operator instruction."""
    message_text = instruction.message_text.strip()
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


async def _process_instruction(
    *,
    runtime: _AgentRuntime,
    instruction: SwitchboardOperatorInstruction,
) -> str:
    """Handle one inbound operator instruction end-to-end."""
    runtime.turn_state.prune_pending_invocations()
    runtime.turn_state.begin_turn_trace()
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
    runtime.turn_state.reset_active_tools()
    runtime.model.last_result = None
    try:
        result = await runtime.agent.run(
            _format_user_prompt(instruction=instruction, context=context)
        )
        response_text = str(result.output).strip()
        if response_text == "":
            response_text = "I do not have a response yet."
    except BrainDependencyError as exc:
        if _is_retryable_lms_throttle(exc):
            _LOGGER.warning(
                "brain agent lms throttled; returning fallback response",
                extra={"operation": exc.operation},
            )
            response_text = _LMS_THROTTLE_RESPONSE
        elif _is_retryable_lms_timeout(exc):
            _LOGGER.warning(
                "brain agent lms timed out; returning fallback response",
                extra={"operation": exc.operation},
            )
            response_text = _LMS_TIMEOUT_RESPONSE
        else:
            raise
    except BrainTransportError as exc:
        if not _is_retryable_lms_transport_timeout(exc):
            raise
        _LOGGER.warning(
            "brain agent lms transport timed out; returning fallback response",
            extra={"operation": exc.operation},
        )
        response_text = _LMS_TIMEOUT_RESPONSE
    chat = runtime.model.last_result
    candidate_turn = await asyncio.to_thread(
        _call_with_optional_meta,
        runtime.client.memory_record_outbound_candidate,
        meta=runtime.turn_state.nested_call_meta(),
        session_id=runtime.session_id,
        content=response_text,
        model="brain-sdk-lms" if chat is None else chat.model,
        provider="brain-sdk" if chat is None else chat.provider,
        token_count=_estimate_token_count(response_text),
        reasoning_level="standard",
    )
    delivered = await _route_outbound_response(
        runtime=runtime,
        instruction=instruction,
        response_text=response_text,
    )
    await asyncio.to_thread(
        _call_with_optional_meta,
        runtime.client.memory_record_outbound_delivery,
        meta=runtime.turn_state.nested_call_meta(),
        session_id=runtime.session_id,
        turn_id=candidate_turn.id,
        delivered=delivered,
    )
    return response_text


async def _route_outbound_response(
    *,
    runtime: _AgentRuntime,
    instruction: SwitchboardOperatorInstruction,
    response_text: str,
) -> bool:
    """Deliver one finalized response via Attention Router notify capability."""
    payload: dict[str, object] = {
        "actor": "operator",
        "channel": instruction.source,
        "message": response_text,
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

    settings = load_actor_settings(config_path=_resolve_config_path())
    core_runtime_settings = load_core_runtime_settings()
    core_settings = core_runtime_settings.core
    _configure_logging(settings=settings)
    heartbeat_path = _resolve_heartbeat_path()
    _write_heartbeat(path=heartbeat_path)

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    client = BrainClient(config=_brain_sdk_config_from_settings(settings))
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
