"""Tests for carrying canonical content parts through PydanticAI user prompts."""

from __future__ import annotations

from pydantic_ai.messages import CachePoint, TextContent, UserPromptPart

from lib.agent.content_parts import as_user_content, stringify_content, to_content_parts
from lib.agent.loop import _build_user_content
from lib.shared.language_model import (
    CachePointContentPart,
    FocusContentPart,
    ReferenceSnippetContentPart,
    TextContentPart,
)


def test_wrapped_parts_round_trip_through_user_prompt_part() -> None:
    """PydanticAI accepts wrapped parts, and unwrapping restores them in order."""
    part = UserPromptPart(
        content=[
            as_user_content(FocusContentPart(text="focus")),
            CachePoint(),
            as_user_content(TextContentPart(text="hello")),
        ]
    )

    assert to_content_parts(part.content) == (
        FocusContentPart(text="focus"),
        CachePointContentPart(),
        TextContentPart(text="hello"),
    )


def test_plain_text_content_becomes_text_part() -> None:
    """A ``TextContent`` without canonical metadata contributes its own text."""
    assert to_content_parts([TextContent(content="hello")]) == (
        TextContentPart(text="hello"),
    )


def test_stringify_content_renders_the_wrapped_part() -> None:
    """Wrapping does not change how a part renders for token estimates."""
    part = FocusContentPart(text="focus")

    assert stringify_content(as_user_content(part)) == stringify_content(part)


def test_headless_user_content_is_a_valid_user_prompt() -> None:
    """The headless loop's prompt passes PydanticAI validation intact."""
    content = _build_user_content(
        prompt="do the thing",
        context_text="background",
        context_environment_items=(),
    )

    part = UserPromptPart(content=content)

    assert to_content_parts(part.content) == (
        ReferenceSnippetContentPart(text="background"),
        TextContentPart(text="do the thing"),
    )
