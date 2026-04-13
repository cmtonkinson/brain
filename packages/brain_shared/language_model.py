"""Shared language-model contracts for Brain inference and prompt exchange."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _ContentPartModel(BaseModel):
    """Base model for one canonical chat content part."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class _InferenceModel(BaseModel):
    """Base model for one canonical provider-agnostic inference contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class TextContentPart(_ContentPartModel):
    """One plain-text content segment."""

    kind: Literal["text"] = "text"
    text: str


class CachePointContentPart(_ContentPartModel):
    """One structural cache boundary marker."""

    kind: Literal["cache_point"] = "cache_point"


class FocusContentPart(_ContentPartModel):
    """One focus-context segment assembled from MAS."""

    kind: Literal["focus"] = "focus"
    text: str


class ConversationSummaryContentPart(_ContentPartModel):
    """One recent-conversation summary segment assembled from MAS."""

    kind: Literal["conversation_summary"] = "conversation_summary"
    text: str


class DialogueTurnContentPart(_ContentPartModel):
    """One dialogue turn segment assembled from MAS history."""

    kind: Literal["dialogue_turn"] = "dialogue_turn"
    role: str
    text: str
    is_summary: bool = False


class ReferenceSnippetContentPart(_ContentPartModel):
    """One reference snippet segment assembled from MAS."""

    kind: Literal["reference_snippet"] = "reference_snippet"
    text: str


class MetadataFieldContentPart(_ContentPartModel):
    """One structured metadata field segment."""

    kind: Literal["metadata_field"] = "metadata_field"
    name: str
    value: str


class OperatorMessageContentPart(_ContentPartModel):
    """One live operator instruction segment."""

    kind: Literal["operator_message"] = "operator_message"
    channel: str
    sender_e164: str
    message_text: str
    approval_intent: str | None = None
    reaction_emoji: str | None = None
    quote_target_timestamp_ms: int | None = None
    reaction_target_timestamp_ms: int | None = None
    reply_to_proposal_token: str | None = None
    reaction_to_proposal_token: str | None = None


class InferenceMeta(_InferenceModel):
    """Trace and session metadata attached to one inference request."""

    trace_id: str
    session_id: str
    source: str
    principal: str
    envelope_id: str | None = None
    parent_id: str | None = None


class InferenceSystemBlock(_InferenceModel):
    """One logical system block assembled by the Agent/SDK."""

    kind: Literal["assistant_persona", "operator_profile", "instructions"]
    text: str
    cache_after: bool = False


class InferenceSystem(_InferenceModel):
    """Canonical system section for one inference request."""

    blocks: tuple[InferenceSystemBlock, ...]


class InferenceReferenceSnippet(_InferenceModel):
    """One MAS-provided reference snippet in the inference context."""

    text: str


class InferenceMemoryTurn(_InferenceModel):
    """One ordered MAS-provided recent turn in the inference context."""

    role: Literal["user", "assistant"]
    text: str
    is_summary: bool


class InferenceMemoryContext(_InferenceModel):
    """The MAS-owned slice of the canonical inference request."""

    current_focus: str | None
    recent_conversation_summary: str
    recent_turns: tuple[InferenceMemoryTurn, ...]
    reference_snippets: tuple[InferenceReferenceSnippet, ...]


class InferenceOperatorMessage(_InferenceModel):
    """One live operator message for the current turn."""

    channel: str
    sender_e164: str
    message_text: str
    approval_intent: str | None = None
    reaction_emoji: str | None = None
    quote_target_timestamp_ms: int | None = None
    reaction_target_timestamp_ms: int | None = None
    reply_to_proposal_token: str | None = None
    reaction_to_proposal_token: str | None = None


class InferenceCurrentTurn(_InferenceModel):
    """The current-turn input owned by the Agent runtime."""

    operator_message: InferenceOperatorMessage


class InferenceToolExecutionHints(_InferenceModel):
    """Agent/runtime hints associated with one callable tool."""

    sequential: bool = False
    requires_approval: bool | None = None


class InferenceToolDefinition(_InferenceModel):
    """One callable tool exposed to the model for this request."""

    name: str
    description: str | None = None
    input_schema: dict[str, object]
    strict_schema: bool | None = None
    execution_hints: InferenceToolExecutionHints = Field(
        default_factory=InferenceToolExecutionHints
    )


class InferenceToolCall(_InferenceModel):
    """One structured tool call emitted by the model within the turn."""

    call_id: str
    tool_name: str
    arguments: dict[str, object]


class InferenceToolResultPayload(_InferenceModel):
    """One structured tool result payload stored in the live event stream."""

    mime_type: str
    text: str | None = None
    data: object | None = None


class InferenceToolResult(_InferenceModel):
    """One structured tool result associated with a prior tool call."""

    call_id: str
    tool_name: str
    status: Literal["success", "empty", "error"] = "success"
    is_error: bool = False
    result: InferenceToolResultPayload


class InferenceAssistantTextEvent(_InferenceModel):
    """One assistant-text event in the ordered live event stream."""

    kind: Literal["assistant_text"] = "assistant_text"
    text: str
    cache_after: bool = False


class InferenceToolCallBatchEvent(_InferenceModel):
    """One ordered batch of tool calls emitted by the assistant."""

    kind: Literal["tool_call_batch"] = "tool_call_batch"
    calls: tuple[InferenceToolCall, ...]
    cache_after: bool = False


class InferenceToolResultBatchEvent(_InferenceModel):
    """One ordered batch of tool results injected back into the turn."""

    kind: Literal["tool_result_batch"] = "tool_result_batch"
    results: tuple[InferenceToolResult, ...]
    cache_after: bool = False


InferenceLiveEvent: TypeAlias = Annotated[
    InferenceAssistantTextEvent
    | InferenceToolCallBatchEvent
    | InferenceToolResultBatchEvent,
    Field(discriminator="kind"),
]


class InferenceToolChoice(_InferenceModel):
    """Provider-agnostic tool-choice policy for one inference request."""

    mode: Literal["auto", "none", "require_any", "require_one"] = "auto"
    tool_name: str | None = None


class InferenceParallelToolCalls(_InferenceModel):
    """Provider-agnostic tool parallelism policy for one inference request."""

    mode: Literal["allow", "forbid"] = "allow"
    max_calls: int | None = None


class InferenceSampling(_InferenceModel):
    """Optional sampling overrides for one inference request."""

    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None


class InferenceControls(_InferenceModel):
    """Non-content generation controls for one inference request."""

    allow_text_output: bool = True
    tool_choice: InferenceToolChoice = Field(default_factory=InferenceToolChoice)
    parallel_tool_calls: InferenceParallelToolCalls = Field(
        default_factory=InferenceParallelToolCalls
    )
    sampling: InferenceSampling = Field(default_factory=InferenceSampling)
    profile: Literal["quick", "standard", "deep"] | None = None

    def model_post_init(self, __context: object) -> None:
        """Validate cross-field control invariants."""
        if (
            self.tool_choice.mode == "require_one"
            and self.tool_choice.tool_name is None
        ):
            raise ValueError("tool_choice.tool_name is required when mode=require_one")
        if (
            self.tool_choice.mode != "require_one"
            and self.tool_choice.tool_name is not None
        ):
            raise ValueError(
                "tool_choice.tool_name is only valid when mode=require_one"
            )
        if (
            self.parallel_tool_calls.max_calls is not None
            and self.parallel_tool_calls.max_calls <= 0
        ):
            raise ValueError("parallel_tool_calls.max_calls must be > 0 when provided")


class InferenceCache(_InferenceModel):
    """Provider-agnostic cache intent for one inference request."""

    mode: Literal["none", "automatic", "explicit"] = "none"
    ttl: str | None = None


class InferenceRequest(_InferenceModel):
    """Canonical provider-agnostic inference request passed across the stack."""

    meta: InferenceMeta
    system: InferenceSystem
    memory_context: InferenceMemoryContext
    current_turn: InferenceCurrentTurn
    tools: tuple[InferenceToolDefinition, ...] = ()
    live_events: tuple[InferenceLiveEvent, ...] = ()
    controls: InferenceControls = Field(default_factory=InferenceControls)
    cache: InferenceCache = Field(default_factory=InferenceCache)


ChatContentPart: TypeAlias = Annotated[
    TextContentPart
    | CachePointContentPart
    | FocusContentPart
    | ConversationSummaryContentPart
    | DialogueTurnContentPart
    | ReferenceSnippetContentPart
    | MetadataFieldContentPart
    | OperatorMessageContentPart,
    Field(discriminator="kind"),
]

_CHAT_CONTENT_PARTS_ADAPTER = TypeAdapter(tuple[ChatContentPart, ...])
_INFERENCE_REQUEST_ADAPTER = TypeAdapter(InferenceRequest)


def validate_chat_content_parts(value: object) -> tuple[ChatContentPart, ...]:
    """Validate one arbitrary payload into canonical chat content parts."""

    return _CHAT_CONTENT_PARTS_ADAPTER.validate_python(value)


def dump_chat_content_parts(
    value: tuple[ChatContentPart, ...],
) -> list[object]:
    """Serialize canonical chat content parts into Python transport data."""

    return list(_CHAT_CONTENT_PARTS_ADAPTER.dump_python(value, mode="python"))


def validate_inference_request(value: object) -> InferenceRequest:
    """Validate one arbitrary payload into a canonical inference request."""

    return _INFERENCE_REQUEST_ADAPTER.validate_python(value)


def dump_inference_request(value: InferenceRequest) -> dict[str, object]:
    """Serialize one canonical inference request into Python transport data."""

    dumped = _INFERENCE_REQUEST_ADAPTER.dump_python(value, mode="python")
    if not isinstance(dumped, dict):
        raise TypeError("dumped inference request must be a dict")
    return dumped
