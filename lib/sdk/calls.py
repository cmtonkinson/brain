"""Thin typed wrappers for Brain Core SDK HTTP operations."""

from __future__ import annotations

import json
from datetime import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lib.sdk.meta import MetaOverrides

from lib.shared.auth.slash_authenticity import SlashAuthenticityProof
from lib.shared.inbound_message import InboundMessage
from lib.sdk.errors import (
    BrainDomainError,
    BrainTransportError,
    BrainValidationError,
    map_transport_error,
    raise_for_domain_errors,
)
from lib.shared.language_model import (
    InferenceRequest,
    dump_inference_request,
)
from lib.shared.ids import generate_ulid_str
from lib.shared.http.errors import HttpRequestError, HttpStatusError


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
class OpDescriptor:
    """SDK-friendly description of one registered Op."""

    op_id: str
    kind: str
    version: str
    summary: str
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    effect: str
    approval: str
    required_ops: tuple[str, ...]
    simple_output_path: str | None = None
    slash_command_name: str | None = None
    slash_command_aliases: tuple[str, ...] = ()
    slash_command_description: str | None = None


@dataclass(frozen=True, slots=True)
class OpSearchHit:
    """Compact semantic op-search result returned by Execution."""

    op_id: str
    required_params: tuple[str, ...]
    summary: str


@dataclass(frozen=True, slots=True)
class DynamicOpClassification:
    """SDK-friendly view of one observed dynamic op classification row."""

    op_id: str
    source_kind: str
    source_ref: str
    summary: str
    effect: str | None
    approval: str | None


@dataclass(frozen=True, slots=True)
class ToolSystemHint:
    """Compact orientation hint for one system reachable through tools."""

    system_id: str
    label: str
    summary: str
    kind: str
    ready: bool | None = None
    tool_count: int | None = None
    pending_tool_count: int | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Policy decision metadata returned from op invocation."""

    decision_id: str
    allowed: bool
    reason_codes: tuple[str, ...]
    obligations: tuple[str, ...]
    proposal_id: str


@dataclass(frozen=True, slots=True)
class OpInvokeResult:
    """SDK-friendly result for one op invocation."""

    output: Any
    policy: PolicyDecision


@dataclass(frozen=True, slots=True)
class LmsChatResult:
    """One direct Language chat result payload."""

    text: str
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class LmsChatToolCall:
    """One normalized tool call returned from the tool-capable Language SDK surface."""

    tool_name: str
    args_json: str
    tool_call_id: str


@dataclass(frozen=True, slots=True)
class LmsToolChatResult:
    """One tool-capable Language response payload."""

    provider: str
    model: str
    finish_reason: str
    text: str | None
    tool_calls: tuple[LmsChatToolCall, ...]


@dataclass(frozen=True, slots=True)
class MemoryDialogueTurn:
    """One Recall dialogue turn in the assembled context payload."""

    role: str
    content: str
    is_summary: bool
    timestamp_ms: int | None = None


@dataclass(frozen=True, slots=True)
class MemoryContextBlock:
    """Full Recall assembled context payload."""

    current_focus: str | None
    recent_conversation_summary: str
    recent_turns: tuple[MemoryDialogueTurn, ...]
    reference_snippets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemoryTurnContext:
    """Recall-resolved turn-start context payload."""

    session_id: str
    inbound_turn: "MemoryTurnRecord"
    context: MemoryContextBlock


@dataclass(frozen=True, slots=True)
class MemoryTurnRecord:
    """One Recall turn record payload."""

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
    """Minimal Recall session reference returned to SDK callers."""

    session_id: str


@dataclass(frozen=True, slots=True)
class ApprovalProposalStatus:
    """Current Policy approval proposal status."""

    proposal_token: str
    status: str
    op_id: str
    actor: str
    channel: str
    expires_at: str | None


@dataclass(frozen=True, slots=True)
class RelayOperatorInstruction:
    """One queued operator instruction delivered from Relay inbound."""

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
    approval_token: str | None = None
    reply_to_proposal_token: str | None = None
    reaction_to_proposal_token: str | None = None


@dataclass(frozen=True, slots=True)
class JobClaimResult:
    """Claimed execution details needed by a Worker Actor to execute a job."""

    execution_id: str
    job_id: str
    op_id: str
    input_payload: dict[str, Any]
    actor: str
    trace_id: str
    parent_envelope_id: str
    attempt_number: int
    max_attempts: int


@dataclass(frozen=True, slots=True)
class RelayInboundIngestResult:
    """Result of ingesting one normalized inbound operator message."""

    queued: bool


@dataclass(frozen=True, slots=True)
class ConsoleResponseMessage:
    """One outbound Brain response delivered via the console channel."""

    message: str
    timestamp_ms: int


@dataclass(frozen=True, slots=True)
class DelegationStarted:
    """Result of one queued delegation invocation request."""

    invocation_id: str


@dataclass(frozen=True, slots=True)
class DelegationStatusView:
    """Read-only state projection for one delegation invocation."""

    invocation_id: str
    status: str
    cancel_reason: str | None
    tokens_in: int
    tokens_out: int
    turn_count: int
    started_at: str | None
    completed_at: str | None


@dataclass(frozen=True, slots=True)
class DelegationResult:
    """Terminal-or-current result projection for one delegation invocation."""

    invocation_id: str
    status: str
    final_response: str | None
    cancel_reason: str | None
    tokens_in: int
    tokens_out: int
    turn_count: int


@dataclass(frozen=True, slots=True)
class DelegationClaim:
    """Claimed invocation details handed to the Subagent Actor."""

    invocation_id: str
    parent_invocation_id: str | None
    principal: str
    channel: str
    personality_id: str
    prompt: str
    context_text: str | None
    context_object_refs: tuple[str, ...]
    tool_allowlist: tuple[str, ...] | None
    max_turns: int
    budget_tokens: int | None
    max_wallclock_seconds: int | None


@dataclass(frozen=True, slots=True)
class DelegationTurnDecision:
    """Per-turn budget evaluation decision returned by Delegation."""

    should_stop: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class DelegationCancelOutcome:
    """Outcome of one cancel request against Delegation."""

    accepted: bool


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


def call_ops_describe(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
) -> tuple[OpDescriptor, ...]:
    """Describe all registered Ops through the Execution HTTP surface."""
    data = _post_json(
        operation="ops.describe",
        http=http,
        url="/ops/describe",
        body=metadata,
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="ops.describe",
        errors=_errors_from_data(data),
    )
    return tuple(_op_descriptor(item) for item in data.get("ops", ()))


def call_ops_list_always_on(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
) -> tuple[OpDescriptor, ...]:
    """Return full descriptors for configured always-on ops."""
    data = _post_json(
        operation="ops.list_always_on",
        http=http,
        url="/ops/always-on",
        body=metadata,
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="ops.list_always_on",
        errors=_errors_from_data(data),
    )
    return tuple(_op_descriptor(item) for item in data.get("ops", ()))


def call_ops_search(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    query: str,
    limit: int | None = None,
) -> tuple[OpSearchHit, ...]:
    """Search the Execution op catalog."""
    data = _post_json(
        operation="ops.search",
        http=http,
        url="/ops/search",
        body={**metadata, "query": query, "limit": limit},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="ops.search",
        errors=_errors_from_data(data),
    )
    return tuple(_op_search_hit(item) for item in data.get("results", ()))


def call_ops_list_dynamic_classifications(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
) -> tuple[DynamicOpClassification, ...]:
    """Return all observed dynamic op classification rows."""
    data = _post_json(
        operation="ops.list_dynamic_classifications",
        http=http,
        url="/ops/dynamic/classifications",
        body=metadata,
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="ops.list_dynamic_classifications",
        errors=_errors_from_data(data),
    )
    return tuple(_dynamic_op_classification(item) for item in data.get("items", ()))


def call_ops_classify_dynamic(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    op_id: str,
    effect: str | None = None,
    approval: str | None = None,
) -> DynamicOpClassification:
    """Persist operator classification (effect and/or approval) for a dynamic op."""
    body: dict[str, object] = {**metadata, "op_id": op_id}
    if effect is not None:
        body["effect"] = effect
    if approval is not None:
        body["approval"] = approval
    data = _post_json(
        operation="ops.classify_dynamic",
        http=http,
        url="/ops/dynamic/classify",
        body=body,
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="ops.classify_dynamic",
        errors=_errors_from_data(data),
    )
    items = data.get("items") or ()
    if not items:
        raise BrainDomainError(
            "ops.classify_dynamic returned no row",
            operation="ops.classify_dynamic",
            details=(),
        )
    return _dynamic_op_classification(items[0])


def _dynamic_op_classification(value: object) -> DynamicOpClassification:
    """Map one raw dynamic-op-classification payload into the SDK dataclass."""
    item = value if isinstance(value, dict) else {}
    effect = item.get("effect")
    approval = item.get("approval")
    return DynamicOpClassification(
        op_id=str(item.get("op_id", "")),
        source_kind=str(item.get("source_kind", "")),
        source_ref=str(item.get("source_ref", "")),
        summary=str(item.get("summary", "")),
        effect=str(effect) if isinstance(effect, str) and effect != "" else None,
        approval=str(approval)
        if isinstance(approval, str) and approval != ""
        else None,
    )


def call_ops_tool_system_hints(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
) -> tuple[ToolSystemHint, ...]:
    """Return compact system-orientation hints for op discovery."""
    data = _post_json(
        operation="ops.tool_system_hints",
        http=http,
        url="/ops/tool-system-hints",
        body=metadata,
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="ops.tool_system_hints",
        errors=_errors_from_data(data),
    )
    return tuple(_tool_system_hint(item) for item in data.get("systems", ()))


def call_op_describe(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    op_id: str,
) -> OpDescriptor:
    """Describe one op through the Execution HTTP surface."""
    data = _post_json(
        operation="ops.describe_one",
        http=http,
        url="/ops/describe-one",
        body={**metadata, "op_id": op_id},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="ops.describe_one",
        errors=_errors_from_data(data),
    )
    op_data = data.get("op")
    if not isinstance(op_data, dict):
        raise BrainDomainError(
            message="ops.describe_one domain failure: missing op",
            operation="ops.describe_one",
        )
    return _op_descriptor(op_data)


def call_slash_lookup(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    name: str,
) -> OpDescriptor | None:
    """Look up one op descriptor by slash command name or alias."""
    data = _post_json(
        operation="ops.slash_lookup",
        http=http,
        url="/ops/slash-lookup",
        body={**metadata, "name": name},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="ops.slash_lookup",
        errors=_errors_from_data(data),
    )
    op_data = data.get("op")
    if op_data is None:
        return None
    if not isinstance(op_data, dict):
        return None
    return _op_descriptor(op_data)


def call_op_invoke(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    op_id: str,
    input_payload: dict[str, Any] | None = None,
    actor: str = "",
    channel: str = "",
    invocation_id: str = "",
    parent_invocation_id: str = "",
    confirmed: bool = False,
    approval_token: str = "",
    reply_to_proposal_token: str = "",
    reaction_to_proposal_token: str = "",
    message_text: str = "",
    slash_authenticity: SlashAuthenticityProof | None = None,
) -> OpInvokeResult:
    """Invoke one Op through the Execution HTTP surface."""
    resolved_invocation_id = invocation_id.strip() or generate_ulid_str()
    data = _post_json(
        operation="ops.invoke",
        http=http,
        url="/ops/invoke",
        body={
            **metadata,
            "op_id": op_id,
            "input_payload": {} if input_payload is None else input_payload,
            "actor": actor,
            "channel": channel,
            "invocation_id": resolved_invocation_id,
            "parent_invocation_id": parent_invocation_id,
            "confirmed": confirmed,
            "approval_token": approval_token,
            "reply_to_proposal_token": reply_to_proposal_token,
            "reaction_to_proposal_token": reaction_to_proposal_token,
            "message_text": message_text,
            "slash_authenticity": (
                slash_authenticity.model_dump(mode="json")
                if slash_authenticity is not None
                else None
            ),
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="ops.invoke",
        errors=_errors_from_data(data),
    )
    return OpInvokeResult(
        output=_decode_output_json(data.get("output_json", "")),
        policy=_policy_decision(data.get("policy", {})),
    )


def call_language_chat(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    system_prompt: str = "",
    prompt: str,
    profile: str = "standard",
) -> LmsChatResult:
    """Execute one direct Language chat call through Core HTTP."""
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


def call_language_chat_with_tools(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    inference_request: InferenceRequest,
) -> LmsToolChatResult:
    """Execute one tool-capable Language chat call through Core HTTP."""
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
        tool_calls=tuple(_language_chat_tool_call(item) for item in tool_calls),
    )


def call_memory_assemble_context(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    session_id: str,
    message: str,
    instruction: RelayOperatorInstruction | None = None,
) -> MemoryTurnContext:
    """Resolve active Recall session, record inbound turn, and return context."""
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


def call_policy_approval_status(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    proposal_token: str,
) -> ApprovalProposalStatus:
    """Return current Policy approval proposal status."""
    data = _post_json(
        operation="policy.approval_status",
        http=http,
        url="/policy/approval_status",
        body={**metadata, "proposal_token": proposal_token},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="policy.approval_status",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise BrainDomainError(
            message="policy.approval_status domain failure: missing payload",
            operation="policy.approval_status",
        )
    return _approval_proposal_status(payload)


def call_policy_approval_response(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    proposal_token: str,
    intent: str,
) -> ApprovalProposalStatus:
    """Record an operator approval response and return current status."""
    data = _post_json(
        operation="policy.approval_response",
        http=http,
        url="/policy/approval_response",
        body={**metadata, "proposal_token": proposal_token, "intent": intent},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="policy.approval_response",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise BrainDomainError(
            message="policy.approval_response domain failure: missing payload",
            operation="policy.approval_response",
        )
    return _approval_proposal_status(payload)


def call_memory_record_inbound_turn(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    session_id: str,
    message: str,
    instruction: RelayOperatorInstruction | None = None,
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


def _instruction_body(instruction: RelayOperatorInstruction) -> dict[str, object]:
    """Serialize one Relay inbound instruction into Recall HTTP payload shape."""
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
        "approval_token": instruction.approval_token,
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
    """Return the historical Recall context snapshot for one session."""
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
    """Create one Recall session and return the new session identifier."""
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
    """Return the latest Recall session id or create one when none exist."""
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
    """Append one outbound Recall response turn."""
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
        op_id=str(action.get("op_id", "")),
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


def call_relay_poll_operator_instruction(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    wait_timeout_seconds: float = 0.0,
) -> RelayOperatorInstruction | None:
    """Poll Relay inbound for the next queued operator instruction."""
    data = _post_json(
        operation="relay.poll_operator_instruction",
        http=http,
        url="/relay/poll_operator_instruction",
        body={
            **metadata,
            "wait_timeout_seconds": wait_timeout_seconds,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="relay.poll_operator_instruction",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise BrainDomainError(
            message="relay.poll_operator_instruction domain failure: invalid payload",
            operation="relay.poll_operator_instruction",
        )
    return _relay_operator_instruction(payload)


def call_relay_ingest_inbound_message(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    message: InboundMessage,
) -> RelayInboundIngestResult:
    """Submit one normalized operator message to Relay inbound for processing."""
    data = _post_json(
        operation="relay.ingest_inbound_message",
        http=http,
        url="/relay/ingest_inbound_message",
        body={
            **metadata,
            "message": message.model_dump(mode="json"),
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="relay.ingest_inbound_message",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if payload is None or not isinstance(payload, dict):
        raise BrainDomainError(
            message="relay.ingest_inbound_message domain failure: invalid payload",
            operation="relay.ingest_inbound_message",
        )
    return RelayInboundIngestResult(queued=bool(payload.get("queued", False)))


def call_relay_poll_console_response(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    wait_timeout_seconds: float = 0.0,
) -> ConsoleResponseMessage | None:
    """Poll Relay inbound for the next queued console response."""
    data = _post_json(
        operation="inbound.poll_console_response",
        http=http,
        url="/relay/poll_console_response",
        body={
            **metadata,
            "wait_timeout_seconds": wait_timeout_seconds,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="inbound.poll_console_response",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise BrainDomainError(
            message="inbound.poll_console_response domain failure: invalid payload",
            operation="inbound.poll_console_response",
        )
    return ConsoleResponseMessage(
        message=str(payload.get("message", "")),
        timestamp_ms=int(payload.get("timestamp_ms", 0)),
    )


_SDK_SPAN_MAX_CHARS = 8_000


def _set_sdk_span_attribute(
    span: object, key: str, value: object, *, enabled: bool
) -> None:
    """Attach one JSON-serialized attribute to a span when capture is enabled."""
    set_attribute = getattr(span, "set_attribute", None)
    if not callable(set_attribute) or not enabled:
        return
    serialized = json.dumps(value, sort_keys=True, default=str)
    set_attribute(key, serialized[:_SDK_SPAN_MAX_CHARS])


def _execute_http_call(
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


def _post_json(
    *,
    operation: str,
    http: object,
    url: str,
    body: dict[str, object],
    timeout_seconds: float,
    method: str = "post",
) -> dict[str, Any]:
    """Issue one HTTP request, annotating an OTel span with input/output."""
    try:
        from opentelemetry import trace as _otel_trace
        from lib.shared.observability import (
            is_llm_content_capture_enabled,
            is_observability_enabled,
        )
    except ImportError:
        return _execute_http_call(
            operation=operation,
            http=http,
            url=url,
            body=body,
            timeout_seconds=timeout_seconds,
            method=method,
        )
    if not is_observability_enabled():
        return _execute_http_call(
            operation=operation,
            http=http,
            url=url,
            body=body,
            timeout_seconds=timeout_seconds,
            method=method,
        )
    capture = is_llm_content_capture_enabled()
    tracer = _otel_trace.get_tracer("brain.sdk")
    with tracer.start_as_current_span(f"sdk.{operation}") as span:
        _set_sdk_span_attribute(
            span, "langfuse.observation.input", body, enabled=capture
        )
        response = _execute_http_call(
            operation=operation,
            http=http,
            url=url,
            body=body,
            timeout_seconds=timeout_seconds,
            method=method,
        )
        _set_sdk_span_attribute(
            span, "langfuse.observation.output", response, enabled=capture
        )
        return response


def _errors_from_data(data: dict[str, Any]) -> list[object]:
    """Return one normalized route-level error list from response JSON."""
    errors = data.get("errors", [])
    if isinstance(errors, list):
        return errors
    return []


def _op_descriptor(value: object) -> OpDescriptor:
    """Map one raw op descriptor payload into the SDK dataclass."""
    item = value if isinstance(value, dict) else {}
    return OpDescriptor(
        op_id=str(item.get("op_id", "")),
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
        effect=str(item.get("effect", "")),
        approval=str(item.get("approval", "")),
        required_ops=tuple(str(entry) for entry in item.get("required_ops", ())),
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


def _op_search_hit(value: object) -> OpSearchHit:
    """Map one raw op search hit payload into the SDK dataclass."""
    item = value if isinstance(value, dict) else {}
    required_params = item.get("required_params", ())
    required_items = required_params if isinstance(required_params, list) else ()
    return OpSearchHit(
        op_id=str(item.get("op_id", "")),
        required_params=tuple(str(entry) for entry in required_items),
        summary=str(item.get("summary", "")),
    )


def _tool_system_hint(value: object) -> ToolSystemHint:
    """Map one raw tool-system hint payload into the SDK dataclass."""
    item = value if isinstance(value, dict) else {}
    ready = item.get("ready")
    tool_count = item.get("tool_count")
    pending = item.get("pending_tool_count")
    return ToolSystemHint(
        system_id=str(item.get("system_id", "")),
        label=str(item.get("label", "")),
        summary=str(item.get("summary", "")),
        kind=str(item.get("kind", "")),
        ready=ready if isinstance(ready, bool) else None,
        tool_count=tool_count if isinstance(tool_count, int) else None,
        pending_tool_count=pending if isinstance(pending, int) else None,
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
    """Decode the Execution stringified output payload into a Python value."""
    text = str(value).strip()
    if text == "":
        return None
    try:
        return json.loads(text)
    except ValueError as exc:
        raise BrainTransportError(
            message="ops.invoke transport failure: invalid output_json payload",
            operation="ops.invoke",
            status_code=200,
            retryable=False,
        ) from exc


def _language_chat_tool_call(data: object) -> LmsChatToolCall:
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


def _memory_turn_record(value: dict[str, Any]) -> MemoryTurnRecord:
    """Map one raw Recall turn payload into the SDK dataclass."""
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
    """Map one raw Recall turn-context payload into the SDK dataclass."""
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
    """Map one raw Recall assembled-context payload into the SDK dataclass."""
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
    """Map one raw Recall dialogue item into the SDK dataclass."""
    item = value if isinstance(value, dict) else {}
    raw_ts = item.get("timestamp_ms")
    return MemoryDialogueTurn(
        role=str(item.get("role", "")),
        content=str(item.get("content", "")),
        is_summary=bool(item.get("is_summary", False)),
        timestamp_ms=None if raw_ts is None else int(raw_ts),
    )


def _approval_proposal_status(value: dict[str, Any]) -> ApprovalProposalStatus:
    """Map one raw Policy approval status payload into SDK dataclass."""
    expires_at = value.get("expires_at")
    return ApprovalProposalStatus(
        proposal_token=str(value.get("proposal_token", "")),
        status=str(value.get("status", "")),
        op_id=str(value.get("op_id", "")),
        actor=str(value.get("actor", "")),
        channel=str(value.get("channel", "")),
        expires_at=None if expires_at is None else str(expires_at),
    )


def _relay_operator_instruction(
    value: dict[str, Any],
) -> RelayOperatorInstruction:
    """Map one raw Relay inbound queue payload into the SDK dataclass."""
    sender = value.get("sender") if isinstance(value.get("sender"), dict) else {}
    thread = value.get("thread") if isinstance(value.get("thread"), dict) else None
    reply_to = (
        value.get("reply_to") if isinstance(value.get("reply_to"), dict) else None
    )
    reaction = (
        value.get("reaction") if isinstance(value.get("reaction"), dict) else None
    )
    reaction_target = (
        reaction.get("target")
        if isinstance(reaction, dict) and isinstance(reaction.get("target"), dict)
        else None
    )
    approval = (
        value.get("approval") if isinstance(value.get("approval"), dict) else None
    )
    return RelayOperatorInstruction(
        sender_e164=str(sender.get("e164", "")),
        message_text=str(value.get("message_text", "")),
        timestamp_ms=int(value.get("timestamp_ms", 0)),
        source_device=str(value.get("source_device", "")),
        source=str(value.get("channel", "")),
        group_id=None if thread is None else str(thread.get("id", "")),
        quote_target_timestamp_ms=None
        if reply_to is None
        else _optional_int(reply_to.get("timestamp_ms")),
        reaction_target_timestamp_ms=None
        if reaction_target is None
        else _optional_int(reaction_target.get("timestamp_ms")),
        reaction_emoji=(
            None
            if not isinstance(reaction, dict) or reaction.get("text") is None
            else str(reaction.get("text"))
        ),
        approval_intent=(None if approval is None else str(approval.get("intent", ""))),
        approval_token=(
            None
            if approval is None or approval.get("token") is None
            else str(approval.get("token"))
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


def describe_ops(
    *,
    client: object,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> tuple[OpDescriptor, ...]:
    """High-level SDK wrapper for Execution op discovery."""
    return client.describe_ops(  # type: ignore[union-attr]
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        )
    )


def list_always_on_ops(
    *,
    client: object,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> tuple[OpDescriptor, ...]:
    """High-level SDK wrapper for always-on Execution op descriptors."""
    return client.list_always_on_ops(  # type: ignore[union-attr]
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        )
    )


def search_ops(
    *,
    client: object,
    query: str,
    limit: int | None = None,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> tuple[OpSearchHit, ...]:
    """High-level SDK wrapper for Execution semantic op search."""
    return client.search_ops(  # type: ignore[union-attr]
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
    """High-level SDK wrapper for op tool-system orientation hints."""
    return client.list_tool_system_hints(  # type: ignore[union-attr]
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def classify_dynamic_op(
    *,
    client: object,
    op_id: str,
    effect: str | None = None,
    approval: str | None = None,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> DynamicOpClassification:
    """High-level SDK wrapper to classify one dynamic op (effect/approval)."""
    return client.classify_dynamic_op(  # type: ignore[union-attr]
        op_id=op_id,
        effect=effect,
        approval=approval,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def describe_op(
    *,
    client: object,
    op_id: str,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> OpDescriptor:
    """High-level SDK wrapper for one Execution op descriptor lookup."""
    return client.describe_op(  # type: ignore[union-attr]
        op_id=op_id,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def invoke_op(
    *,
    client: object,
    op_id: str,
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
) -> OpInvokeResult:
    """High-level SDK wrapper for Execution op invocation."""
    return client.invoke_op(  # type: ignore[union-attr]
        op_id=op_id,
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


def language_chat(
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
    """High-level SDK wrapper for direct Language chat."""
    return client.language_chat(  # type: ignore[union-attr]
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


def language_chat_with_tools(
    *,
    client: object,
    inference_request: InferenceRequest,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> LmsToolChatResult:
    """High-level SDK wrapper for tool-capable Language chat."""
    return client.language_chat_with_tools(  # type: ignore[union-attr]
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
    """High-level SDK wrapper for Recall turn-context assembly."""
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
    instruction: RelayOperatorInstruction | None = None,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> MemoryTurnRecord:
    """High-level SDK wrapper for Recall inbound-turn recording."""
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
    """High-level SDK wrapper for Recall snapshot assembly."""
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
    """High-level SDK wrapper for Recall create-session."""
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
    """High-level SDK wrapper for Recall get-latest-or-create-session."""
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
    """High-level SDK wrapper for Recall outbound-candidate recording."""
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
    """High-level SDK wrapper for Recall outbound-delivery recording."""
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
    """High-level SDK wrapper for Recall record-response."""
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


def relay_poll_operator_instruction(
    *,
    client: object,
    wait_timeout_seconds: float = 0.0,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> RelayOperatorInstruction | None:
    """High-level SDK wrapper for dequeuing one queued operator instruction."""
    return client.relay_poll_operator_instruction(  # type: ignore[union-attr]
        wait_timeout_seconds=wait_timeout_seconds,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def relay_ingest_inbound_message(
    *,
    client: object,
    message: InboundMessage,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> RelayInboundIngestResult:
    """High-level SDK wrapper for submitting one normalized inbound message."""
    return client.relay_ingest_inbound_message(  # type: ignore[union-attr]
        message=message,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def relay_poll_console_response(
    *,
    client: object,
    wait_timeout_seconds: float = 0.0,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> ConsoleResponseMessage | None:
    """High-level SDK wrapper for polling the next queued console response."""
    return client.relay_poll_console_response(  # type: ignore[union-attr]
        wait_timeout_seconds=wait_timeout_seconds,
        meta=_meta_overrides(
            principal=principal,
            source=source,
            trace_id=trace_id,
            parent_id=parent_id,
        ),
    )


def _delegation_invoke_body(
    *,
    metadata: dict[str, object],
    prompt: str,
    context_text: str | None,
    context_object_refs: tuple[str, ...],
    personality_id: str,
    tool_allowlist: tuple[str, ...] | None,
    max_turns: int,
    budget_tokens: int | None,
    max_wallclock_seconds: int | None,
    parent_invocation_id: str | None,
    timeout_seconds: float | None = None,
) -> dict[str, object]:
    """Project delegation invoke parameters into a stable HTTP body."""
    body: dict[str, object] = {
        **metadata,
        "prompt": prompt,
        "context_text": context_text,
        "context_object_refs": list(context_object_refs),
        "personality_id": personality_id,
        "tool_allowlist": (None if tool_allowlist is None else list(tool_allowlist)),
        "max_turns": max_turns,
        "budget_tokens": budget_tokens,
        "max_wallclock_seconds": max_wallclock_seconds,
        "parent_invocation_id": parent_invocation_id,
    }
    if timeout_seconds is not None:
        body["timeout_seconds"] = timeout_seconds
    return body


def call_delegation_invoke(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    prompt: str,
    context_text: str | None = None,
    context_object_refs: tuple[str, ...] = (),
    personality_id: str = "subagent",
    tool_allowlist: tuple[str, ...] | None = None,
    max_turns: int = 8,
    budget_tokens: int | None = None,
    max_wallclock_seconds: int | None = None,
    parent_invocation_id: str | None = None,
) -> DelegationStarted:
    """Queue one delegated invocation and return the new invocation id."""
    data = _post_json(
        operation="delegation.invoke",
        http=http,
        url="/delegation/invoke",
        body=_delegation_invoke_body(
            metadata=metadata,
            prompt=prompt,
            context_text=context_text,
            context_object_refs=context_object_refs,
            personality_id=personality_id,
            tool_allowlist=tool_allowlist,
            max_turns=max_turns,
            budget_tokens=budget_tokens,
            max_wallclock_seconds=max_wallclock_seconds,
            parent_invocation_id=parent_invocation_id,
        ),
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="delegation.invoke",
        errors=_errors_from_data(data),
    )
    return DelegationStarted(
        invocation_id=str(_payload_dict(data).get("invocation_id", "")),
    )


def call_delegation_invoke_and_wait(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    prompt: str,
    context_text: str | None = None,
    context_object_refs: tuple[str, ...] = (),
    personality_id: str = "subagent",
    tool_allowlist: tuple[str, ...] | None = None,
    max_turns: int = 8,
    budget_tokens: int | None = None,
    max_wallclock_seconds: int | None = None,
    parent_invocation_id: str | None = None,
    wait_timeout_seconds: float | None = None,
) -> DelegationResult:
    """Queue one delegated invocation and block until terminal state."""
    data = _post_json(
        operation="delegation.invoke_and_wait",
        http=http,
        url="/delegation/invoke-and-wait",
        body=_delegation_invoke_body(
            metadata=metadata,
            prompt=prompt,
            context_text=context_text,
            context_object_refs=context_object_refs,
            personality_id=personality_id,
            tool_allowlist=tool_allowlist,
            max_turns=max_turns,
            budget_tokens=budget_tokens,
            max_wallclock_seconds=max_wallclock_seconds,
            parent_invocation_id=parent_invocation_id,
            timeout_seconds=wait_timeout_seconds,
        ),
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="delegation.invoke_and_wait",
        errors=_errors_from_data(data),
    )
    return _to_delegation_result(_payload_dict(data))


def call_delegation_wait(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    invocation_id: str,
    wait_timeout_seconds: float | None = None,
) -> DelegationResult:
    """Block until the named invocation reaches terminal state."""
    body: dict[str, object] = {**metadata, "invocation_id": invocation_id}
    if wait_timeout_seconds is not None:
        body["timeout_seconds"] = wait_timeout_seconds
    data = _post_json(
        operation="delegation.wait",
        http=http,
        url="/delegation/wait",
        body=body,
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="delegation.wait",
        errors=_errors_from_data(data),
    )
    return _to_delegation_result(_payload_dict(data))


def call_delegation_status(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    invocation_id: str,
) -> DelegationStatusView:
    """Return the current status projection for one invocation."""
    data = _post_json(
        operation="delegation.status",
        http=http,
        url="/delegation/status",
        body={**metadata, "invocation_id": invocation_id},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="delegation.status",
        errors=_errors_from_data(data),
    )
    return _to_delegation_status(_payload_dict(data))


def call_delegation_cancel(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    invocation_id: str,
    reason: str = "manual",
) -> DelegationCancelOutcome:
    """Request cancellation of one queued or running invocation."""
    data = _post_json(
        operation="delegation.cancel",
        http=http,
        url="/delegation/cancel",
        body={**metadata, "invocation_id": invocation_id, "reason": reason},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="delegation.cancel",
        errors=_errors_from_data(data),
    )
    payload = _payload_dict(data)
    return DelegationCancelOutcome(accepted=bool(payload.get("accepted", False)))


def call_delegation_claim_invocation(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    claimed_by: str = "subagent",
) -> DelegationClaim | None:
    """Claim the oldest queued invocation for a Subagent Actor."""
    data = _post_json(
        operation="delegation.claim",
        http=http,
        url="/delegation/claim",
        body={**metadata, "claimed_by": claimed_by},
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="delegation.claim",
        errors=_errors_from_data(data),
    )
    payload = data.get("payload")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        return None
    return _to_delegation_claim(payload)


def call_delegation_record_turn(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    invocation_id: str,
) -> DelegationTurnDecision:
    """Bump turn count and re-evaluate budget against the audit trail."""
    data = _post_json(
        operation="delegation.record_turn",
        http=http,
        url="/delegation/record-turn",
        body={
            **metadata,
            "invocation_id": invocation_id,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="delegation.record_turn",
        errors=_errors_from_data(data),
    )
    payload = _payload_dict(data)
    reason = payload.get("reason")
    return DelegationTurnDecision(
        should_stop=bool(payload.get("should_stop", False)),
        reason=None if reason is None else str(reason),
    )


def call_delegation_finalize_invocation(
    *,
    http: object,
    metadata: dict[str, object],
    timeout_seconds: float,
    invocation_id: str,
    status: str,
    final_response: str | None = None,
    transcript_ref: str | None = None,
    cancel_reason: str | None = None,
) -> DelegationResult:
    """Apply a terminal status transition to one invocation."""
    data = _post_json(
        operation="delegation.finalize",
        http=http,
        url="/delegation/finalize",
        body={
            **metadata,
            "invocation_id": invocation_id,
            "status": status,
            "final_response": final_response,
            "transcript_ref": transcript_ref,
            "cancel_reason": cancel_reason,
        },
        timeout_seconds=timeout_seconds,
    )
    raise_for_domain_errors(
        operation="delegation.finalize",
        errors=_errors_from_data(data),
    )
    return _to_delegation_result(_payload_dict(data))


def _payload_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce one envelope-shaped HTTP response payload into a dict."""
    payload = data.get("payload")
    if isinstance(payload, dict):
        return payload
    return {}


def _to_delegation_result(payload: dict[str, Any]) -> DelegationResult:
    """Project one delegation result payload dict into the SDK dataclass."""
    return DelegationResult(
        invocation_id=str(payload.get("invocation_id", "")),
        status=str(payload.get("status", "")),
        final_response=(
            None
            if payload.get("final_response") is None
            else str(payload.get("final_response", ""))
        ),
        cancel_reason=(
            None
            if payload.get("cancel_reason") is None
            else str(payload.get("cancel_reason", ""))
        ),
        tokens_in=int(payload.get("tokens_in", 0)),
        tokens_out=int(payload.get("tokens_out", 0)),
        turn_count=int(payload.get("turn_count", 0)),
    )


def _to_delegation_status(payload: dict[str, Any]) -> DelegationStatusView:
    """Project one delegation status payload dict into the SDK dataclass."""
    started_at = payload.get("started_at")
    completed_at = payload.get("completed_at")
    return DelegationStatusView(
        invocation_id=str(payload.get("invocation_id", "")),
        status=str(payload.get("status", "")),
        cancel_reason=(
            None
            if payload.get("cancel_reason") is None
            else str(payload.get("cancel_reason", ""))
        ),
        tokens_in=int(payload.get("tokens_in", 0)),
        tokens_out=int(payload.get("tokens_out", 0)),
        turn_count=int(payload.get("turn_count", 0)),
        started_at=None if started_at is None else str(started_at),
        completed_at=None if completed_at is None else str(completed_at),
    )


def _to_delegation_claim(payload: dict[str, Any]) -> DelegationClaim:
    """Project one delegation claim payload dict into the SDK dataclass."""
    parent = payload.get("parent_invocation_id")
    refs = payload.get("context_object_refs") or ()
    if not isinstance(refs, list | tuple):
        refs = ()
    allowlist = payload.get("tool_allowlist")
    if allowlist is not None and not isinstance(allowlist, list | tuple):
        allowlist = None
    return DelegationClaim(
        invocation_id=str(payload.get("invocation_id", "")),
        parent_invocation_id=None if parent is None else str(parent),
        principal=str(payload.get("principal", "")),
        channel=str(payload.get("channel", "")),
        personality_id=str(payload.get("personality_id", "")),
        prompt=str(payload.get("prompt", "")),
        context_text=(
            None
            if payload.get("context_text") is None
            else str(payload.get("context_text", ""))
        ),
        context_object_refs=tuple(str(item) for item in refs),
        tool_allowlist=(
            None if allowlist is None else tuple(str(item) for item in allowlist)
        ),
        max_turns=int(payload.get("max_turns", 0)),
        budget_tokens=(
            None
            if payload.get("budget_tokens") is None
            else int(payload.get("budget_tokens", 0))
        ),
        max_wallclock_seconds=(
            None
            if payload.get("max_wallclock_seconds") is None
            else int(payload.get("max_wallclock_seconds", 0))
        ),
    )


def _meta_overrides(
    *,
    principal: str = "",
    source: str = "",
    trace_id: str | None = None,
    parent_id: str | None = None,
) -> MetaOverrides | None:
    """Return MetaOverrides only when at least one non-default value is supplied."""
    from lib.sdk.meta import MetaOverrides

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
