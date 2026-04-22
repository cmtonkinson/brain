"""Thin typed wrappers for Brain Core SDK HTTP operations."""

from __future__ import annotations

import json
from datetime import datetime
from dataclasses import dataclass
from typing import Any

from packages.brain_sdk.errors import (
    BrainDomainError,
    BrainTransportError,
    BrainValidationError,
    map_transport_error,
    raise_for_domain_errors,
)
from packages.brain_shared.language_model import (
    InferenceRequest,
    dump_inference_request,
)
from packages.brain_shared.ids import generate_ulid_str
from packages.brain_shared.http.errors import HttpRequestError, HttpStatusError


@dataclass(frozen=True, slots=True)
class CoreComponentHealth:
    """Aggregate readiness for one Core component."""

    ready: bool
    detail: str


@dataclass(frozen=True, slots=True)
class CoreHealthResult:
    """Aggregate Core health status."""

    ready: bool
    services: dict[str, CoreComponentHealth]
    resources: dict[str, CoreComponentHealth]


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """SDK-friendly description of one registered Capability."""

    capability_id: str
    kind: str
    version: str
    summary: str
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    autonomy: int
    requires_approval: bool
    side_effects: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    simple_output_path: str | None = None
    slash_command_name: str | None = None
    slash_command_aliases: tuple[str, ...] = ()
    slash_command_description: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilitySearchHit:
    """Compact semantic capability-search result returned by CES."""

    capability_id: str
    required_params: tuple[str, ...]
    summary: str


@dataclass(frozen=True, slots=True)
class ToolSystemHint:
    """Compact orientation hint for one system reachable through tools."""

    system_id: str
    label: str
    summary: str
    kind: str
    ready: bool | None = None
    tool_count: int | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Policy decision metadata returned from capability invocation."""

    decision_id: str
    allowed: bool
    reason_codes: tuple[str, ...]
    obligations: tuple[str, ...]
    proposal_id: str


@dataclass(frozen=True, slots=True)
class CapabilityInvokeResult:
    """SDK-friendly result for one capability invocation."""

    output: Any
    policy: PolicyDecision


@dataclass(frozen=True, slots=True)
class LmsChatResult:
    """One direct LMS chat result payload."""

    text: str
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class LmsChatToolCall:
    """One normalized tool call returned from the tool-capable LMS SDK surface."""

    tool_name: str
    args_json: str
    tool_call_id: str


@dataclass(frozen=True, slots=True)
class LmsToolChatResult:
    """One tool-capable LMS response payload."""

    provider: str
    model: str
    finish_reason: str
    text: str | None
    tool_calls: tuple[LmsChatToolCall, ...]


@dataclass(frozen=True, slots=True)
class MemoryDialogueTurn:
    """One MAS dialogue turn in the assembled context payload."""

    role: str
    content: str
    is_summary: bool


@dataclass(frozen=True, slots=True)
class MemoryContextBlock:
    """Full MAS assembled context payload."""

    current_focus: str | None
    recent_conversation_summary: str
    recent_turns: tuple[MemoryDialogueTurn, ...]
    reference_snippets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemoryTurnContext:
    """MAS-resolved turn-start context payload."""

    session_id: str
    inbound_turn: "MemoryTurnRecord"
    context: MemoryContextBlock


@dataclass(frozen=True, slots=True)
class MemoryTurnRecord:
    """One MAS turn record payload."""

    id: str
    session_id: str
    direction: str
    content: str
    role: str
    model: str | None
    provider: str | None
    token_count: int | None
    reasoning_level: str | None
    trace_id: str
    conversation_episode_id: str
    principal: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MemorySessionRef:
    """Minimal MAS session reference returned to SDK callers."""

    session_id: str


@dataclass(frozen=True, slots=True)
class SwitchboardOperatorInstruction:
    """One queued operator instruction delivered from Switchboard."""

    sender_e164: str
    message_text: str
    timestamp_ms: int
    source_device: str
    source: str
    group_id: str | None
    quote_target_timestamp_ms: int | None
    reaction_target_timestamp_ms: int | None
    reaction_emoji: str | None = None
    approval_intent: str | None = None
    reply_to_proposal_token: str | None = None
    reaction_to_proposal_token: str | None = None


def call_core_health(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
) -> CoreHealthResult:
    """Execute one Core health request and map response payload."""
    data = _post_json(
        operation="core.health",
        http=http,
        url="/health",
        body=metadata,
        timeout_seconds=timeout_seconds,
        method="get",
    )
    services = {
        k: CoreComponentHealth(
            ready=bool(v.get("ready")), detail=str(v.get("detail", ""))
        )
        for k, v in data.get("services", {}).items()
    }
    resources = {
        k: CoreComponentHealth(
            ready=bool(v.get("ready")), detail=str(v.get("detail", ""))
        )
        for k, v in data.get("resources", {}).items()
    }
    return CoreHealthResult(
        ready=bool(data.get("ready")),
        services=services,
        resources=resources,
    )


def call_capabilities_describe(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
) -> tuple[CapabilityDescriptor, ...]:
    """Describe all registered Capabilities through the CES HTTP surface."""
    data = _post_json(
        operation="capabilities.describe",
        http=http,
        url="/capabilities/describe",
        body=metadata,
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="capabilities.describe",
        errors=_errors_from_data(data),
    )
    return tuple(_capability_descriptor(item) for item in data.get("capabilities", ()))


def call_capabilities_list_always_on(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
) -> tuple[CapabilityDescriptor, ...]:
    """Return full descriptors for configured always-on capabilities."""
    data = _post_json(
        operation="capabilities.list_always_on",
        http=http,
        url="/capabilities/always-on",
        body=metadata,
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="capabilities.list_always_on",
        errors=_errors_from_data(data),
    )
    return tuple(_capability_descriptor(item) for item in data.get("capabilities", ()))


def call_capabilities_search(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    query: str,
    limit: int | None = None,
) -> tuple[CapabilitySearchHit, ...]:
    """Search the CES capability catalog."""
    data = _post_json(
        operation="capabilities.search",
        http=http,
        url="/capabilities/search",
        body={**metadata, "query": query, "limit": limit},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="capabilities.search",
        errors=_errors_from_data(data),
    )
    return tuple(_capability_search_hit(item) for item in data.get("results", ()))


def call_capabilities_tool_system_hints(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
) -> tuple[ToolSystemHint, ...]:
    """Return compact system-orientation hints for capability discovery."""
    data = _post_json(
        operation="capabilities.tool_system_hints",
        http=http,
        url="/capabilities/tool-system-hints",
        body=metadata,
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="capabilities.tool_system_hints",
        errors=_errors_from_data(data),
    )
    return tuple(_tool_system_hint(item) for item in data.get("systems", ()))


def call_capability_describe(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    capability_id: str,
) -> CapabilityDescriptor:
    """Describe one capability through the CES HTTP surface."""
    data = _post_json(
        operation="capabilities.describe_one",
        http=http,
        url="/capabilities/describe-one",
        body={**metadata, "capability_id": capability_id},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="capabilities.describe_one",
        errors=_errors_from_data(data),
    )
    capability = data.get("capability")
    if not isinstance(capability, dict):
        raise BrainDomainError(
            message="capabilities.describe_one domain failure: missing capability",
            operation="capabilities.describe_one",
        )
    return _capability_descriptor(capability)


def call_slash_lookup(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    name: str,
) -> CapabilityDescriptor | None:
    """Look up one capability descriptor by slash command name or alias."""
    data = _post_json(
        operation="capabilities.slash_lookup",
        http=http,
        url="/capabilities/slash-lookup",
        body={**metadata, "name": name},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="capabilities.slash_lookup",
        errors=_errors_from_data(data),
    )
    capability = data.get("capability")
    if capability is None:
        return None
    if not isinstance(capability, dict):
        return None
    return _capability_descriptor(capability)


def call_capability_invoke(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    capability_id: str,
    input_payload: dict[str, Any] | None = None,
    actor: str = "",
    channel: str = "",
    invocation_id: str = "",
    parent_invocation_id: str = "",
    confirmed: bool = False,
    approval_token: str = "",
    reply_to_proposal_token: str = "",
    reaction_to_proposal_token: str = "",
) -> CapabilityInvokeResult:
    """Invoke one Capability through the CES HTTP surface."""
    resolved_invocation_id = invocation_id.strip() or generate_ulid_str()
    data = _post_json(
        operation="capabilities.invoke",
        http=http,
        url="/capabilities/invoke",
        body={
            **metadata,
            "capability_id": capability_id,
            "input_payload": {} if input_payload is None else input_payload,
            "actor": actor,
            "channel": channel,
            "invocation_id": resolved_invocation_id,
            "parent_invocation_id": parent_invocation_id,
            "confirmed": confirmed,
            "approval_token": approval_token,
            "reply_to_proposal_token": reply_to_proposal_token,
            "reaction_to_proposal_token": reaction_to_proposal_token,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="capabilities.invoke",
        errors=_errors_from_data(data),
    )
    return CapabilityInvokeResult(
        output=_decode_output_json(data.get("output_json", "")),
        policy=_policy_decision(data.get("policy", {})),
    )


def call_lms_chat(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    system_prompt: str = "",
    prompt: str,
    profile: str = "standard",
) -> LmsChatResult:
    """Execute one direct LMS chat call through Core HTTP."""
    data = _post_json(
        operation="lms.chat",
        http=http,
        url="/lms/chat",
        body={
            **metadata,
            "system_prompt": system_prompt,
            "prompt": prompt,
            "profile": profile,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="lms.chat",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise BrainDomainError(
            message="lms.chat domain failure: missing payload",
            operation="lms.chat",
        )
    return LmsChatResult(
        text=str(payload.get("text", "")),
        provider=str(payload.get("provider", "")),
        model=str(payload.get("model", "")),
    )


def call_lms_chat_with_tools(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    inference_request: InferenceRequest,
) -> LmsToolChatResult:
    """Execute one tool-capable LMS chat call through Core HTTP."""
    data = _post_json(
        operation="lms.chat_with_tools",
        http=http,
        url="/lms/chat-with-tools",
        body={
            **metadata,
            "inference_request": dump_inference_request(inference_request),
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="lms.chat_with_tools",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise BrainDomainError(
            message="lms.chat_with_tools domain failure: missing payload",
            operation="lms.chat_with_tools",
        )
    tool_calls = payload.get("tool_calls", ())
    if not isinstance(tool_calls, list):
        raise BrainDomainError(
            message="lms.chat_with_tools domain failure: invalid tool_calls",
            operation="lms.chat_with_tools",
        )
    return LmsToolChatResult(
        provider=str(payload.get("provider", "")),
        model=str(payload.get("model", "")),
        finish_reason=str(payload.get("finish_reason", "")),
        text=None if payload.get("text") is None else str(payload.get("text", "")),
        tool_calls=tuple(_lms_chat_tool_call(item) for item in tool_calls),
    )


def call_memory_assemble_context(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    session_id: str,
    message: str,
    instruction: SwitchboardOperatorInstruction | None = None,
) -> MemoryTurnContext:
    """Resolve active MAS session, record inbound turn, and return context."""
    instruction_body: dict[str, object] | None = None
    if instruction is not None:
        instruction_body = _instruction_body(instruction)
    data = _post_json(
        operation="memory.assemble_context",
        http=http,
        url="/memory/assemble_context",
        body={
            **metadata,
            "session_id": session_id,
            "message": message,
            "instruction": instruction_body,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="memory.assemble_context",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise BrainDomainError(
            message="memory.assemble_context domain failure: missing payload",
            operation="memory.assemble_context",
        )
    return _memory_turn_context(payload)


def call_memory_record_inbound_turn(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    session_id: str,
    message: str,
    instruction: SwitchboardOperatorInstruction | None = None,
) -> MemoryTurnRecord:
    """Persist one inbound turn and return the recorded turn payload."""
    instruction_body: dict[str, object] | None = None
    if instruction is not None:
        instruction_body = _instruction_body(instruction)
    data = _post_json(
        operation="memory.record_inbound_turn",
        http=http,
        url="/memory/record_inbound_turn",
        body={
            **metadata,
            "session_id": session_id,
            "message": message,
            "instruction": instruction_body,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="memory.record_inbound_turn",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise BrainDomainError(
            message="memory.record_inbound_turn domain failure: missing payload",
            operation="memory.record_inbound_turn",
        )
    return _memory_turn_record(payload)


def _instruction_body(instruction: SwitchboardOperatorInstruction) -> dict[str, object]:
    """Serialize one Switchboard instruction into MAS HTTP payload shape."""
    return {
        "sender_e164": instruction.sender_e164,
        "message_text": instruction.message_text,
        "timestamp_ms": instruction.timestamp_ms,
        "source_device": instruction.source_device,
        "source": instruction.source,
        "group_id": instruction.group_id,
        "quote_target_timestamp_ms": instruction.quote_target_timestamp_ms,
        "reaction_target_timestamp_ms": instruction.reaction_target_timestamp_ms,
        "reaction_emoji": instruction.reaction_emoji,
        "approval_intent": instruction.approval_intent,
        "reply_to_proposal_token": instruction.reply_to_proposal_token,
        "reaction_to_proposal_token": instruction.reaction_to_proposal_token,
    }


def call_memory_assemble_snapshot(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    session_id: str,
    exclude_latest: bool = True,
) -> MemoryContextBlock:
    """Return the historical MAS context snapshot for one session."""
    data = _post_json(
        operation="memory.assemble_snapshot",
        http=http,
        url="/memory/assemble_snapshot",
        body={
            **metadata,
            "session_id": session_id,
            "exclude_latest": exclude_latest,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="memory.assemble_snapshot",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise BrainDomainError(
            message="memory.assemble_snapshot domain failure: missing payload",
            operation="memory.assemble_snapshot",
        )
    return _memory_context_block(payload)


def call_memory_record_outbound_candidate(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    session_id: str,
    content: str,
    model: str,
    provider: str,
    token_count: int,
    reasoning_level: str,
) -> MemoryTurnRecord:
    """Persist one outbound candidate turn and return the recorded turn payload."""
    data = _post_json(
        operation="memory.record_outbound_candidate",
        http=http,
        url="/memory/record_outbound_candidate",
        body={
            **metadata,
            "session_id": session_id,
            "content": content,
            "model": model,
            "provider": provider,
            "token_count": token_count,
            "reasoning_level": reasoning_level,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="memory.record_outbound_candidate",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise BrainDomainError(
            message="memory.record_outbound_candidate domain failure: missing payload",
            operation="memory.record_outbound_candidate",
        )
    return _memory_turn_record(payload)


def call_memory_record_outbound_delivery(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    session_id: str,
    turn_id: str,
    delivered: bool,
) -> bool:
    """Persist one outbound delivery result."""
    data = _post_json(
        operation="memory.record_outbound_delivery",
        http=http,
        url="/memory/record_outbound_delivery",
        body={
            **metadata,
            "session_id": session_id,
            "turn_id": turn_id,
            "delivered": delivered,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="memory.record_outbound_delivery",
        errors=_errors_from_data(data),
    )
    return bool(data.get("payload"))


def call_memory_create_session(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
) -> MemorySessionRef:
    """Create one MAS session and return the new session identifier."""
    data = _post_json(
        operation="memory.create_session",
        http=http,
        url="/memory/create_session",
        body=metadata,
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="memory.create_session",
        errors=_errors_from_data(data),
    )
    session_id = str(data.get("session_id", "")).strip()
    if session_id == "":
        raise BrainDomainError(
            message="memory.create_session domain failure: missing session_id",
            operation="memory.create_session",
        )
    return MemorySessionRef(session_id=session_id)


def call_memory_get_latest_or_create_session(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
) -> MemorySessionRef:
    """Return the latest MAS session id or create one when none exist."""
    data = _post_json(
        operation="memory.get_latest_or_create_session",
        http=http,
        url="/memory/get_latest_or_create_session",
        body=metadata,
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="memory.get_latest_or_create_session",
        errors=_errors_from_data(data),
    )
    session_id = str(data.get("session_id", "")).strip()
    if session_id == "":
        raise BrainDomainError(
            message="memory.get_latest_or_create_session domain failure: missing session_id",
            operation="memory.get_latest_or_create_session",
        )
    return MemorySessionRef(session_id=session_id)


def call_memory_compact_dialogue(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    session_id: str,
) -> MemorySessionRef:
    """Force-summarize all visible turns and advance dialogue frontier."""
    data = _post_json(
        operation="memory.compact_dialogue",
        http=http,
        url="/memory/compact_dialogue",
        body={**metadata, "session_id": session_id},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="memory.compact_dialogue",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise BrainDomainError(
            message="memory.compact_dialogue domain failure: missing payload",
            operation="memory.compact_dialogue",
        )
    sid = str(payload.get("id", "")).strip()
    if sid == "":
        raise BrainDomainError(
            message="memory.compact_dialogue domain failure: missing session id",
            operation="memory.compact_dialogue",
        )
    return MemorySessionRef(session_id=sid)


def call_memory_record_response(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    session_id: str,
    content: str,
    model: str,
    provider: str,
    token_count: int,
    reasoning_level: str,
) -> bool:
    """Append one outbound MAS response turn."""
    data = _post_json(
        operation="memory.record_response",
        http=http,
        url="/memory/record_response",
        body={
            **metadata,
            "session_id": session_id,
            "content": content,
            "model": model,
            "provider": provider,
            "token_count": token_count,
            "reasoning_level": reasoning_level,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="memory.record_response",
        errors=_errors_from_data(data),
    )
    return bool(data.get("payload"))


@dataclass(frozen=True, slots=True)
class JobClaimResult:
    """Claimed execution details needed by a Worker Actor to execute a job."""

    execution_id: str
    job_id: str
    capability_id: str
    input_payload: dict[str, Any]
    actor: str
    trace_id: str
    parent_envelope_id: str
    attempt_number: int
    max_attempts: int


def call_job_claim_execution(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    worker_id: str = "worker",
) -> JobClaimResult | None:
    """Claim the next queued job execution for a Worker Actor.

    Returns None when no queued execution is available.
    """
    data = _post_json(
        operation="jobs.executions.claim",
        http=http,
        url="/jobs/executions/claim",
        body={**metadata, "worker_id": worker_id},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="jobs.executions.claim",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        return None
    execution = payload.get("execution") or {}
    intent = payload.get("intent") or {}
    action = intent.get("action") or {}
    if not isinstance(execution, dict):
        return None
    return JobClaimResult(
        execution_id=str(execution.get("id", "")),
        job_id=str(execution.get("job_id", "")),
        capability_id=str(action.get("capability_id", "")),
        input_payload=dict(action.get("input_payload") or {}),
        actor=str(intent.get("created_by_actor", "")),
        trace_id=str(execution.get("trace_id", "")),
        parent_envelope_id=str(execution.get("parent_envelope_id", "")),
        attempt_number=int(execution.get("attempt_number", 1)),
        max_attempts=int(execution.get("max_attempts", 1)),
    )


def call_job_complete_execution(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    execution_id: str,
) -> None:
    """Report a successful execution result to the Job Service."""
    data = _post_json(
        operation="jobs.executions.complete",
        http=http,
        url="/jobs/executions/complete",
        body={**metadata, "execution_id": execution_id},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="jobs.executions.complete",
        errors=_errors_from_data(data),
    )


def call_job_fail_execution(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    execution_id: str,
    error_message: str,
    error_code: str | None = None,
    is_retryable: bool = False,
) -> None:
    """Report a failed execution result to the Job Service."""
    data = _post_json(
        operation="jobs.executions.fail",
        http=http,
        url="/jobs/executions/fail",
        body={
            **metadata,
            "execution_id": execution_id,
            "error_message": error_message,
            "error_code": error_code,
            "is_retryable": is_retryable,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="jobs.executions.fail",
        errors=_errors_from_data(data),
    )


def call_switchboard_poll_operator_instruction(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    wait_timeout_seconds: float = 0.0,
) -> SwitchboardOperatorInstruction | None:
    """Poll Switchboard for the next queued operator instruction."""
    data = _post_json(
        operation="switchboard.poll_operator_instruction",
        http=http,
        url="/switchboard/poll_operator_instruction",
        body={
            **metadata,
            "wait_timeout_seconds": wait_timeout_seconds,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="switchboard.poll_operator_instruction",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise BrainDomainError(
            message="switchboard.poll_operator_instruction domain failure: invalid payload",
            operation="switchboard.poll_operator_instruction",
        )
    return _switchboard_operator_instruction(payload)


@dataclass(frozen=True, slots=True)
class ConsoleEnqueueResult:
    """Result of enqueuing one console operator message."""

    queued: bool


@dataclass(frozen=True, slots=True)
class ConsoleResponseMessage:
    """One outbound Brain response delivered via the console channel."""

    message: str
    timestamp_ms: int


def call_switchboard_enqueue_console(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    message_text: str,
) -> ConsoleEnqueueResult:
    """Submit one console operator message to Switchboard for processing."""
    data = _post_json(
        operation="switchboard.enqueue_console",
        http=http,
        url="/switchboard/enqueue_console_message",
        body={
            **metadata,
            "message_text": message_text,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="switchboard.enqueue_console",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if payload is None or not isinstance(payload, dict):
        raise BrainDomainError(
            message="switchboard.enqueue_console domain failure: invalid payload",
            operation="switchboard.enqueue_console",
        )
    return ConsoleEnqueueResult(queued=bool(payload.get("queued", False)))


def call_switchboard_poll_console_response(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    wait_timeout_seconds: float = 0.0,
) -> ConsoleResponseMessage | None:
    """Poll Attention Router for the next queued console response."""
    data = _post_json(
        operation="switchboard.poll_console_response",
        http=http,
        url="/attention-router/poll_console_response",
        body={
            **metadata,
            "wait_timeout_seconds": wait_timeout_seconds,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="switchboard.poll_console_response",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise BrainDomainError(
            message="switchboard.poll_console_response domain failure: invalid payload",
            operation="switchboard.poll_console_response",
        )
    return ConsoleResponseMessage(
        message=str(payload.get("message", "")),
        timestamp_ms=int(payload.get("timestamp_ms", 0)),
    )


def _post_json(
    *,
    operation: str,
    http: object,
    url: str,
    body: dict[str, object],
    timeout_seconds: float,
    method: str = "post",
) -> dict[str, Any]:
    """Issue one HTTP request and return the JSON response dict."""
    try:
        if method == "get":
            return http.get_json(  # type: ignore[union-attr]
                url,
                timeout=timeout_seconds,
                log_operation=operation,
            )
        return http.post_json(  # type: ignore[union-attr]
            url,
            json=body,
            timeout=timeout_seconds,
            log_operation=operation,
        )
    except HttpStatusError as exc:
        retryable = exc.status_code >= 500 or exc.status_code == 429
        raise map_transport_error(
            operation=operation,
            status_code=exc.status_code,
            message=exc.response_body or str(exc),
            retryable=retryable,
        ) from exc
    except HttpRequestError as exc:
        raise BrainTransportError(
            message=f"{operation} transport failure: {exc}",
            operation=operation,
            status_code=0,
            retryable=True,
        ) from exc


def _errors_from_data(data: dict[str, Any]) -> list[object]:
    """Return one normalized route-level error list from response JSON."""
    errors = data.get("errors", [])
    if isinstance(errors, list):
        return errors
    return []


def _capability_descriptor(value: object) -> CapabilityDescriptor:
    """Map one raw capability descriptor payload into the SDK dataclass."""
    item = value if isinstance(value, dict) else {}
    return CapabilityDescriptor(
        capability_id=str(item.get("capability_id", "")),
        kind=str(item.get("kind", "")),
        version=str(item.get("version", "")),
        summary=str(item.get("summary", "")),
        input_schema=_schema(item.get("input_schema")),
        output_schema=_schema(item.get("output_schema")),
        simple_output_path=(
            None
            if item.get("simple_output_path") is None
            else str(item.get("simple_output_path"))
        ),
        autonomy=int(item.get("autonomy", 0)),
        requires_approval=bool(item.get("requires_approval", False)),
        side_effects=tuple(str(entry) for entry in item.get("side_effects", ())),
        required_capabilities=tuple(
            str(entry) for entry in item.get("required_capabilities", ())
        ),
        slash_command_name=(
            None
            if item.get("slash_command_name") is None
            else str(item.get("slash_command_name"))
        ),
        slash_command_aliases=tuple(
            str(entry) for entry in item.get("slash_command_aliases", ())
        ),
        slash_command_description=(
            None
            if item.get("slash_command_description") is None
            else str(item.get("slash_command_description"))
        ),
    )


def _capability_search_hit(value: object) -> CapabilitySearchHit:
    """Map one raw capability search hit payload into the SDK dataclass."""
    item = value if isinstance(value, dict) else {}
    required_params = item.get("required_params", ())
    required_items = required_params if isinstance(required_params, list) else ()
    return CapabilitySearchHit(
        capability_id=str(item.get("capability_id", "")),
        required_params=tuple(str(entry) for entry in required_items),
        summary=str(item.get("summary", "")),
    )


def _tool_system_hint(value: object) -> ToolSystemHint:
    """Map one raw tool-system hint payload into the SDK dataclass."""
    item = value if isinstance(value, dict) else {}
    ready = item.get("ready")
    tool_count = item.get("tool_count")
    return ToolSystemHint(
        system_id=str(item.get("system_id", "")),
        label=str(item.get("label", "")),
        summary=str(item.get("summary", "")),
        kind=str(item.get("kind", "")),
        ready=ready if isinstance(ready, bool) else None,
        tool_count=tool_count if isinstance(tool_count, int) else None,
    )


def _schema(value: object) -> dict[str, Any] | None:
    """Return one schema payload when it is object-shaped."""
    if not isinstance(value, dict):
        return None
    return dict(value)


def _policy_decision(value: object) -> PolicyDecision:
    """Map one raw policy payload into the SDK dataclass."""
    item = value if isinstance(value, dict) else {}
    return PolicyDecision(
        decision_id=str(item.get("decision_id", "")),
        allowed=bool(item.get("allowed", False)),
        reason_codes=tuple(str(entry) for entry in item.get("reason_codes", ())),
        obligations=tuple(str(entry) for entry in item.get("obligations", ())),
        proposal_id=str(item.get("proposal_id", "")),
    )


def _decode_output_json(value: object) -> Any:
    """Decode the CES stringified output payload into a Python value."""
    text = str(value).strip()
    if text == "":
        return None
    try:
        return json.loads(text)
    except ValueError as exc:
        raise BrainTransportError(
            message="capabilities.invoke transport failure: invalid output_json payload",
            operation="capabilities.invoke",
            status_code=200,
            retryable=False,
        ) from exc


def _lms_chat_tool_call(data: object) -> LmsChatToolCall:
    """Map one tool call wire payload into an SDK dataclass."""
    if not isinstance(data, dict):
        raise BrainValidationError(
            message="lms.chat_with_tools returned an invalid tool call payload",
            operation="lms.chat_with_tools",
        )
    return LmsChatToolCall(
        tool_name=str(data.get("tool_name", "")),
        args_json=str(data.get("args_json", "")),
        tool_call_id=str(data.get("tool_call_id", "")),
    )


def _lms_chat_tool_call_payload(value: LmsChatToolCall) -> dict[str, object]:
    """Serialize one tool call dataclass for transport."""
    return {
        "tool_name": value.tool_name,
        "args_json": value.args_json,
        "tool_call_id": value.tool_call_id,
    }


def _memory_turn_record(value: dict[str, Any]) -> MemoryTurnRecord:
    """Map one raw MAS turn payload into the SDK dataclass."""
    return MemoryTurnRecord(
        id=str(value.get("id", "")),
        session_id=str(value.get("session_id", "")),
        direction=str(value.get("direction", "")),
        content=str(value.get("content", "")),
        role=str(value.get("role", "")),
        model=None if value.get("model") is None else str(value.get("model")),
        provider=None if value.get("provider") is None else str(value.get("provider")),
        token_count=(
            None if value.get("token_count") is None else int(value.get("token_count"))
        ),
        reasoning_level=(
            None
            if value.get("reasoning_level") is None
            else str(value.get("reasoning_level"))
        ),
        trace_id=str(value.get("trace_id", "")),
        conversation_episode_id=str(value.get("conversation_episode_id", "")),
        principal=str(value.get("principal", "")),
        created_at=datetime.fromisoformat(str(value.get("created_at"))),
    )


def _memory_turn_context(value: dict[str, Any]) -> MemoryTurnContext:
    """Map one raw MAS turn-context payload into the SDK dataclass."""
    inbound = value.get("inbound_turn")
    context = value.get("context")
    if not isinstance(inbound, dict) or not isinstance(context, dict):
        raise BrainDomainError(
            message="memory.assemble_context domain failure: invalid payload",
            operation="memory.assemble_context",
        )
    return MemoryTurnContext(
        session_id=str(value.get("session_id", "")),
        inbound_turn=_memory_turn_record(inbound),
        context=_memory_context_block(context),
    )


def _memory_context_block(value: dict[str, Any]) -> MemoryContextBlock:
    """Map one raw MAS assembled-context payload into the SDK dataclass."""
    recent_turns = value.get("recent_turns", [])
    recent_turn_items = recent_turns if isinstance(recent_turns, list) else []
    snippets = value.get("reference_snippets", [])
    snippet_items = snippets if isinstance(snippets, list) else []
    return MemoryContextBlock(
        current_focus=(
            None
            if value.get("current_focus") is None
            else str(value.get("current_focus"))
        ),
        recent_conversation_summary=str(value.get("recent_conversation_summary", "")),
        recent_turns=tuple(_memory_dialogue_turn(item) for item in recent_turn_items),
        reference_snippets=tuple(str(item) for item in snippet_items),
    )


def _memory_dialogue_turn(value: object) -> MemoryDialogueTurn:
    """Map one raw MAS dialogue item into the SDK dataclass."""
    item = value if isinstance(value, dict) else {}
    return MemoryDialogueTurn(
        role=str(item.get("role", "")),
        content=str(item.get("content", "")),
        is_summary=bool(item.get("is_summary", False)),
    )


def _switchboard_operator_instruction(
    value: dict[str, Any],
) -> SwitchboardOperatorInstruction:
    """Map one raw Switchboard queue payload into the SDK dataclass."""
    return SwitchboardOperatorInstruction(
        sender_e164=str(value.get("sender_e164", "")),
        message_text=str(value.get("message_text", "")),
        timestamp_ms=int(value.get("timestamp_ms", 0)),
        source_device=str(value.get("source_device", "")),
        source=str(value.get("source", "")),
        group_id=None if value.get("group_id") is None else str(value.get("group_id")),
        quote_target_timestamp_ms=_optional_int(value.get("quote_target_timestamp_ms")),
        reaction_target_timestamp_ms=_optional_int(
            value.get("reaction_target_timestamp_ms")
        ),
        reaction_emoji=(
            None
            if value.get("reaction_emoji") is None
            else str(value.get("reaction_emoji"))
        ),
        approval_intent=(
            None
            if value.get("approval_intent") is None
            else str(value.get("approval_intent"))
        ),
        reply_to_proposal_token=(
            None
            if value.get("reply_to_proposal_token") is None
            else str(value.get("reply_to_proposal_token"))
        ),
        reaction_to_proposal_token=(
            None
            if value.get("reaction_to_proposal_token") is None
            else str(value.get("reaction_to_proposal_token"))
        ),
    )


def _optional_int(value: object) -> int | None:
    """Return one optional integer value when present and parseable."""
    if value is None:
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def core_health(
    *,
    client: object,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> CoreHealthResult:
    """High-level SDK wrapper for Core health checks."""
    return client.core_health(  # type: ignore[union-attr]
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        )
    )


def describe_capabilities(
    *,
    client: object,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> tuple[CapabilityDescriptor, ...]:
    """High-level SDK wrapper for CES capability discovery."""
    return client.describe_capabilities(  # type: ignore[union-attr]
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        )
    )


def list_always_on_capabilities(
    *,
    client: object,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> tuple[CapabilityDescriptor, ...]:
    """High-level SDK wrapper for always-on CES capability descriptors."""
    return client.list_always_on_capabilities(  # type: ignore[union-attr]
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        )
    )


def search_capabilities(
    *,
    client: object,
    query: str,
    limit: int | None = None,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> tuple[CapabilitySearchHit, ...]:
    """High-level SDK wrapper for CES semantic capability search."""
    return client.search_capabilities(  # type: ignore[union-attr]
        query=query,
        limit=limit,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def list_tool_system_hints(
    *,
    client: object,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> tuple[ToolSystemHint, ...]:
    """High-level SDK wrapper for capability tool-system orientation hints."""
    return client.list_tool_system_hints(  # type: ignore[union-attr]
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def describe_capability(
    *,
    client: object,
    capability_id: str,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> CapabilityDescriptor:
    """High-level SDK wrapper for one CES capability descriptor lookup."""
    return client.describe_capability(  # type: ignore[union-attr]
        capability_id=capability_id,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def invoke_capability(
    *,
    client: object,
    capability_id: str,
    input_payload: dict[str, Any] | None = None,
    actor: str = "",
    channel: str = "",
    invocation_id: str = "",
    parent_invocation_id: str = "",
    confirmed: bool = False,
    approval_token: str = "",
    reply_to_proposal_token: str = "",
    reaction_to_proposal_token: str = "",
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> CapabilityInvokeResult:
    """High-level SDK wrapper for CES capability invocation."""
    return client.invoke_capability(  # type: ignore[union-attr]
        capability_id=capability_id,
        input_payload={} if input_payload is None else input_payload,
        actor=actor,
        channel=channel,
        invocation_id=invocation_id,
        parent_invocation_id=parent_invocation_id,
        confirmed=confirmed,
        approval_token=approval_token,
        reply_to_proposal_token=reply_to_proposal_token,
        reaction_to_proposal_token=reaction_to_proposal_token,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def lms_chat(
    *,
    client: object,
    system_prompt: str = "",
    prompt: str,
    profile: str = "standard",
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> LmsChatResult:
    """High-level SDK wrapper for direct LMS chat."""
    return client.lms_chat(  # type: ignore[union-attr]
        system_prompt=system_prompt,
        prompt=prompt,
        profile=profile,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def lms_chat_with_tools(
    *,
    client: object,
    inference_request: InferenceRequest,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> LmsToolChatResult:
    """High-level SDK wrapper for tool-capable LMS chat."""
    return client.lms_chat_with_tools(  # type: ignore[union-attr]
        inference_request=inference_request,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def memory_assemble_context(
    *,
    client: object,
    session_id: str,
    message: str,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> MemoryTurnContext:
    """High-level SDK wrapper for MAS turn-context assembly."""
    return client.memory_assemble_context(  # type: ignore[union-attr]
        session_id=session_id,
        message=message,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def memory_record_inbound_turn(
    *,
    client: object,
    session_id: str,
    message: str,
    instruction: SwitchboardOperatorInstruction | None = None,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> MemoryTurnRecord:
    """High-level SDK wrapper for MAS inbound-turn recording."""
    return client.memory_record_inbound_turn(  # type: ignore[union-attr]
        session_id=session_id,
        message=message,
        instruction=instruction,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def memory_assemble_snapshot(
    *,
    client: object,
    session_id: str,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> MemoryContextBlock:
    """High-level SDK wrapper for MAS snapshot assembly."""
    return client.memory_assemble_snapshot(  # type: ignore[union-attr]
        session_id=session_id,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def memory_create_session(
    *,
    client: object,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> MemorySessionRef:
    """High-level SDK wrapper for MAS create-session."""
    return client.memory_create_session(  # type: ignore[union-attr]
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        )
    )


def memory_get_latest_or_create_session(
    *,
    client: object,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> MemorySessionRef:
    """High-level SDK wrapper for MAS get-latest-or-create-session."""
    return client.memory_get_latest_or_create_session(  # type: ignore[union-attr]
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        )
    )


def memory_record_outbound_candidate(
    *,
    client: object,
    session_id: str,
    content: str,
    model: str,
    provider: str,
    token_count: int,
    reasoning_level: str,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> MemoryTurnRecord:
    """High-level SDK wrapper for MAS outbound-candidate recording."""
    return client.memory_record_outbound_candidate(  # type: ignore[union-attr]
        session_id=session_id,
        content=content,
        model=model,
        provider=provider,
        token_count=token_count,
        reasoning_level=reasoning_level,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def memory_record_outbound_delivery(
    *,
    client: object,
    session_id: str,
    turn_id: str,
    delivered: bool,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> bool:
    """High-level SDK wrapper for MAS outbound-delivery recording."""
    return client.memory_record_outbound_delivery(  # type: ignore[union-attr]
        session_id=session_id,
        turn_id=turn_id,
        delivered=delivered,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def memory_record_response(
    *,
    client: object,
    session_id: str,
    content: str,
    model: str,
    provider: str,
    token_count: int,
    reasoning_level: str,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> bool:
    """High-level SDK wrapper for MAS record-response."""
    return client.memory_record_response(  # type: ignore[union-attr]
        session_id=session_id,
        content=content,
        model=model,
        provider=provider,
        token_count=token_count,
        reasoning_level=reasoning_level,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def switchboard_poll_operator_instruction(
    *,
    client: object,
    wait_timeout_seconds: float = 0.0,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> SwitchboardOperatorInstruction | None:
    """High-level SDK wrapper for dequeuing one queued operator instruction."""
    return client.switchboard_poll_operator_instruction(  # type: ignore[union-attr]
        wait_timeout_seconds=wait_timeout_seconds,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def _meta_overrides(
    *,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> object:
    """Build metadata overrides only when call-site values are provided."""
    from packages.brain_sdk.meta import MetaOverrides

    has_values = any(
        (
            principal != "",
            source != "",
            trace_id is not None,
            parent_id is not None,
        )
    )
    if not has_values:
        return None
    return MetaOverrides(
        principal=principal or None,
        source=source or None,
        trace_id=trace_id,
        parent_id="" if parent_id is None else parent_id,
    )
