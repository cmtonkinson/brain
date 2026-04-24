"""Build canonical ``InferenceRequest`` payloads from PydanticAI history.

This module is the authoritative converter both ``actors/assistant`` and
``actors/subagent`` route every Language turn through. The function
``build_inference_request`` translates PydanticAI's internal
message envelope (``ModelRequest``/``ModelResponse``) into the
provider-neutral ``InferenceRequest`` the SDK transport surface accepts.

Companion helpers convert tool-return parts and tool-definition shapes,
and classify tool-result payloads into ``success``/``empty``/``error``
status codes for downstream consumers.

All functions here are pure and side-effect-free; agent-specific tool
schema augmentation is supplied by the caller via the
``extra_input_properties`` argument to ``to_inference_tool_definition``.
"""

from __future__ import annotations

import json
from typing import Literal, Mapping

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.tools import ToolDefinition

from lib.agent.inference import decode_tool_args_json
from lib.agent.content_parts import (
    contains_context_content_parts,
    content_parts_are_only_cache_points,
    extract_context_from_content_parts,
    mark_cache_after_last_live_event,
    stringify_content,
    text_from_content_parts,
    to_content_parts,
)
from lib.sdk.meta import MetaOverrides
from lib.shared.language_model import (
    CachePointContentPart,
    InferenceAssistantTextEvent,
    InferenceCache,
    InferenceControls,
    InferenceCurrentTurn,
    InferenceEnvironmentContext,
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
)


_VALID_PROFILES: frozenset[str] = frozenset({"quick", "standard", "deep"})
"""Known profile names accepted by ``InferenceControls``; anything else maps to ``None``."""


def build_inference_request(
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
    tool_approvals: dict[str, str | None],
    extra_input_properties: Mapping[str, object] | None = None,
) -> InferenceRequest:
    """Build one canonical inference request from PydanticAI history + runtime state.

    ``extra_input_properties`` are merged into every advertised tool's
    ``input_schema.properties`` map; the operator-facing Agent uses this
    to inject its agent-only context properties (e.g. quote/operator hints)
    while the Subagent leaves it ``None`` for clean op-only schemas.
    """
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
                    content_parts = to_content_parts(part.content)
                    if any(
                        isinstance(item, CachePointContentPart)
                        for item in content_parts
                    ):
                        explicit_cache = True
                    if not context_found and contains_context_content_parts(
                        content_parts
                    ):
                        (
                            current_focus,
                            recent_conversation_summary,
                            recent_turns,
                            reference_snippets,
                            environment_context,
                            operator_message,
                        ) = extract_context_from_content_parts(content_parts)
                        context_found = True
                        continue
                    if content_parts_are_only_cache_points(content_parts):
                        if len(tool_results) > 0:
                            tool_results_cache_after = True
                        else:
                            mark_cache_after_last_live_event(live_events)
                        continue
                    if operator_message is None and len(content_parts) > 0:
                        fallback_text = text_from_content_parts(content_parts).strip()
                        if fallback_text != "":
                            operator_message = InferenceOperatorMessage(
                                channel="",
                                sender_e164="",
                                message_text=fallback_text,
                            )
                    continue
                if isinstance(part, ToolReturnPart):
                    tool_results.append(tool_return_part_to_inference_result(part))
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
                        arguments=tool_args_object(part.args),
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
            to_inference_tool_definition(
                item,
                approval=tool_approvals.get(item.name),
                extra_input_properties=extra_input_properties,
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
            profile=profile if profile in _VALID_PROFILES else None,
        ),
        cache=InferenceCache(mode="explicit" if explicit_cache else "none"),
    )


def tool_args_json(value: str | dict[str, object] | None) -> str:
    """Convert one tool-call args payload into canonical JSON text."""
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def tool_args_object(value: str | dict[str, object] | None) -> dict[str, object]:
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


def tool_return_part_to_inference_result(part: ToolReturnPart) -> InferenceToolResult:
    """Convert one tool return part into a canonical structured tool result."""
    status = classify_tool_result_status(part.content)
    payload = tool_result_payload_from_content(part.content)
    return InferenceToolResult(
        call_id=part.tool_call_id,
        tool_name=part.tool_name,
        status=status,
        is_error=(status == "error"),
        result=payload,
    )


def classify_tool_result_status(value: object) -> Literal["success", "empty", "error"]:
    """Classify one tool result as success, empty, or error."""
    if is_tool_error_payload(value):
        return "error"
    if is_empty_tool_result(value):
        return "empty"
    return "success"


def is_tool_error_payload(value: object) -> bool:
    """Return True when one tool result matches the agent error payload shape."""
    if isinstance(value, dict):
        return (
            isinstance(value.get("error"), str)
            and isinstance(value.get("message"), str)
            and isinstance(value.get("op_id"), str)
        )
    if not isinstance(value, str):
        return False
    try:
        payload = json.loads(value)
    except ValueError:
        return False
    return isinstance(payload, dict) and is_tool_error_payload(payload)


def is_empty_tool_result(value: object) -> bool:
    """Return True when one tool result is semantically empty but not erroneous."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in {"", "null", "[]", "{}"}
    if isinstance(value, list | tuple | dict | set | frozenset):
        return len(value) == 0
    return False


def tool_result_payload_from_content(value: object) -> InferenceToolResultPayload:
    """Convert one arbitrary tool result into canonical structured payload fields."""
    if value is None:
        return InferenceToolResultPayload(mime_type="text/plain", text="")
    if isinstance(value, str):
        if is_empty_tool_result(value):
            return InferenceToolResultPayload(mime_type="text/plain", text="")
        return InferenceToolResultPayload(mime_type="text/plain", text=value)
    if isinstance(value, dict | list | tuple):
        return InferenceToolResultPayload(
            mime_type="application/json",
            data=value,
        )
    return InferenceToolResultPayload(
        mime_type="text/plain",
        text=stringify_content(value),
    )


def is_not_found_tool_result(value: object) -> bool:
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


def to_model_tool_call(value: object) -> ToolCallPart:
    """Convert one SDK ``LmsChatToolCall`` into a PydanticAI response part.

    Accepts the SDK-side dataclass duck-typed via attributes so this helper
    can stay free of an explicit dependency on the SDK error/calls module
    layout (callers always supply an ``LmsChatToolCall``).
    """
    tool_name = str(getattr(value, "tool_name", ""))
    args_json = str(getattr(value, "args_json", ""))
    tool_call_id = str(getattr(value, "tool_call_id", ""))
    return ToolCallPart(
        tool_name=tool_name,
        args=decode_tool_args_json(args_json),
        tool_call_id=tool_call_id,
    )


def allow_parallel_tool_calls(
    *,
    messages: list[ModelRequest | ModelResponse],
    discovery_tool_names: frozenset[str] = frozenset(),
) -> bool:
    """Return whether the current hop can safely permit parallel tool calls.

    Disables parallelism for the turn immediately following any of the
    configured ``discovery_tool_names`` (the operator-facing Agent uses
    this to suppress parallelism right after ``search_tools`` /
    ``get_tool_info`` calls). Headless callers pass an empty set to
    always allow parallelism.
    """
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        saw_tool_return = False
        for part in message.parts:
            if not isinstance(part, ToolReturnPart):
                continue
            saw_tool_return = True
            if part.tool_name in discovery_tool_names:
                return False
        if saw_tool_return:
            return True
    return True


def to_inference_tool_definition(
    value: ToolDefinition,
    *,
    approval: str | None,
    extra_input_properties: Mapping[str, object] | None = None,
) -> InferenceToolDefinition:
    """Convert one PydanticAI tool definition into a canonical inference tool.

    When ``extra_input_properties`` is supplied, it is merged into the
    advertised tool's ``input_schema.properties`` map so callers can inject
    runtime-supplied properties (e.g. agent-only conversational hints)
    without rewriting individual tool schemas.
    """
    schema = dict(value.parameters_json_schema)
    if extra_input_properties:
        schema = _merge_input_properties(schema, extra_input_properties)
    return InferenceToolDefinition(
        name=value.name,
        input_schema=schema,
        description=value.description,
        strict_schema=value.strict,
        execution_hints=InferenceToolExecutionHints(
            sequential=value.sequential,
            approval=None if approval is None else str(approval),
        ),
    )


def _merge_input_properties(
    schema: dict[str, object],
    extra_input_properties: Mapping[str, object],
) -> dict[str, object]:
    """Merge runtime-supplied properties into an advertised tool schema."""
    properties = schema.get("properties", {})
    merged_properties = (
        {**properties, **dict(extra_input_properties)}
        if isinstance(properties, dict)
        else dict(extra_input_properties)
    )
    return {
        **schema,
        "properties": merged_properties,
        "additionalProperties": False,
    }


__all__ = [
    "allow_parallel_tool_calls",
    "build_inference_request",
    "classify_tool_result_status",
    "is_empty_tool_result",
    "is_not_found_tool_result",
    "is_tool_error_payload",
    "to_inference_tool_definition",
    "to_model_tool_call",
    "tool_args_json",
    "tool_args_object",
    "tool_result_payload_from_content",
    "tool_return_part_to_inference_result",
]
