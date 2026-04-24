"""Pure helpers operating on PydanticAI ``ChatContentPart`` payloads.

Stateless and side-effect-free; reshape user prompt content into either a
canonical ``ChatContentPart`` tuple or extract structured memory/operator
context for the inference IR.
"""

from __future__ import annotations

import json

from pydantic_ai.messages import CachePoint

from lib.shared.language_model import (
    CachePointContentPart,
    ChatContentPart,
    ConversationSummaryContentPart,
    DialogueTurnContentPart,
    EnvironmentContextContentPart,
    FocusContentPart,
    InferenceAssistantTextEvent,
    InferenceEnvironmentContext,
    InferenceEnvironmentItem,
    InferenceMemoryTurn,
    InferenceOperatorMessage,
    InferenceReferenceSnippet,
    InferenceToolCallBatchEvent,
    InferenceToolResultBatchEvent,
    OperatorMessageContentPart,
    ReferenceSnippetContentPart,
    TextContentPart,
)


# Tuple of every type that ``to_content_parts`` recognizes as a structured
# content carrier; anything outside falls through to JSON-stringification.
CONTENT_PART_TYPES: tuple[type, ...] = (
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


def stringify_content(value: object) -> str:
    """Render one structured content value into a stable compact string."""
    if isinstance(value, str):
        return value
    if isinstance(value, list | tuple):
        if all(isinstance(item, CONTENT_PART_TYPES) for item in value):
            parts: list[str] = []
            for item in value:
                if isinstance(item, CachePoint):
                    continue
                parts.append(stringify_content(item))
            return "".join(parts)
        try:
            return json.dumps(value, sort_keys=True)
        except TypeError:
            return str(value)
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)


def content_has_cache_point(value: object) -> bool:
    """Return whether one structured user-content payload already includes cache."""
    if isinstance(value, CachePoint):
        return True
    if isinstance(value, list | tuple):
        return any(content_has_cache_point(item) for item in value)
    return False


def to_content_parts(value: object) -> tuple[ChatContentPart, ...]:
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
        if all(isinstance(item, CONTENT_PART_TYPES) for item in value):
            parts: list[ChatContentPart] = []
            for item in value:
                parts.extend(to_content_parts(item))
            return tuple(parts)
        rendered = stringify_content(value)
        if rendered == "":
            return ()
        return (TextContentPart(text=rendered),)
    rendered = stringify_content(value)
    if rendered == "":
        return ()
    return (TextContentPart(text=rendered),)


def contains_context_content_parts(parts: tuple[ChatContentPart, ...]) -> bool:
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


def content_parts_are_only_cache_points(parts: tuple[ChatContentPart, ...]) -> bool:
    """Return True when a user prompt contains only structural cache markers."""
    return len(parts) > 0 and all(
        isinstance(item, CachePointContentPart) for item in parts
    )


def extract_context_from_content_parts(
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


def text_from_content_parts(parts: tuple[ChatContentPart, ...]) -> str:
    """Render only text-bearing content parts into one fallback string."""
    segments: list[str] = []
    for item in parts:
        if isinstance(item, TextContentPart):
            segments.append(item.text)
    return "\n".join(segment for segment in segments if segment != "")


def mark_cache_after_last_live_event(
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


__all__ = [
    "CONTENT_PART_TYPES",
    "content_has_cache_point",
    "content_parts_are_only_cache_points",
    "contains_context_content_parts",
    "extract_context_from_content_parts",
    "mark_cache_after_last_live_event",
    "stringify_content",
    "text_from_content_parts",
    "to_content_parts",
]
