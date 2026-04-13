"""Pydantic ingress validation models for Language Model Service."""

from __future__ import annotations

from enum import StrEnum
from typing import Sequence

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from services.action.language_model.domain import (
    ChatMessage,
    ChatToolCall,
    ChatToolDefinition,
)


class ReasoningLevel(StrEnum):
    """Supported chat reasoning selectors."""

    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


class EmbeddingProfile(StrEnum):
    """Supported embedding profile selectors."""

    DOCUMENT_EMBEDDING = "document_embedding"
    CAPABILITY_EMBEDDING = "capability_embedding"


class _ValidationModel(BaseModel):
    """Base strict request-validation model."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def _require_text(value: str, *, field_name: str) -> str:
    """Require one non-empty string value."""
    normalized = value.strip()
    if normalized == "":
        raise ValueError(f"{field_name} is required")
    return normalized


def _require_text_items(values: Sequence[str], *, field_name: str) -> tuple[str, ...]:
    """Require one non-empty batch of non-empty strings."""
    if len(values) == 0:
        raise ValueError(f"{field_name} must not be empty")
    normalized: list[str] = []
    for index, value in enumerate(values):
        text = value.strip()
        if text == "":
            raise ValueError(f"{field_name}[{index}] is required")
        normalized.append(text)
    return tuple(normalized)


class ChatRequest(_ValidationModel):
    """Validated request shape for single chat generation."""

    system_prompt: str = ""
    prompt: str
    profile: ReasoningLevel

    @field_validator("system_prompt")
    @classmethod
    def _normalize_system_prompt(cls, value: str) -> str:
        """Normalize optional system prompt text."""
        return value.strip()

    @field_validator("prompt")
    @classmethod
    def _validate_prompt(cls, value: str, info: ValidationInfo) -> str:
        """Validate one non-empty prompt."""
        return _require_text(value, field_name=info.field_name)


class ChatBatchRequest(_ValidationModel):
    """Validated request shape for batch chat generation."""

    prompts: tuple[str, ...]
    profile: ReasoningLevel

    @field_validator("prompts")
    @classmethod
    def _validate_prompts(
        cls, value: Sequence[str], info: ValidationInfo
    ) -> tuple[str, ...]:
        """Validate one non-empty prompt list."""
        return _require_text_items(value, field_name=info.field_name)


class ChatToolCallModel(ChatToolCall):
    """Validated tool call payload used in tool-capable requests."""

    @field_validator("tool_name", "args_json", "tool_call_id")
    @classmethod
    def _validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        """Require non-empty tool call fields."""
        return _require_text(value, field_name=info.field_name)


class ChatToolDefinitionModel(ChatToolDefinition):
    """Validated tool definition payload for tool-capable chat."""

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str, info: ValidationInfo) -> str:
        """Require a non-empty tool name."""
        return _require_text(value, field_name=info.field_name)


class ChatMessageModel(ChatMessage):
    """Validated chat history message for tool-capable chat."""

    tool_calls: tuple[ChatToolCallModel, ...] = ()

    @field_validator("role")
    @classmethod
    def _validate_role(cls, value: str, info: ValidationInfo) -> str:
        """Restrict chat message roles to the supported normalized set."""
        normalized = _require_text(value, field_name=info.field_name).lower()
        if normalized not in {"system", "user", "assistant", "tool"}:
            raise ValueError("role must be system, user, assistant, or tool")
        return normalized

    @field_validator("content")
    @classmethod
    def _normalize_content(cls, value: str) -> str:
        """Normalize content while allowing empty assistant/tool placeholders."""
        return value.strip()

    @field_validator("tool_name", "tool_call_id")
    @classmethod
    def _normalize_optional_text(cls, value: str) -> str:
        """Normalize optional tool metadata fields."""
        return value.strip()


class ChatWithToolsRequest(_ValidationModel):
    """Validated request shape for one tool-capable chat completion."""

    messages: tuple[ChatMessageModel, ...]
    tools: tuple[ChatToolDefinitionModel, ...] = ()
    tool_choice: str | dict[str, object] | None = None
    parallel_tool_calls: bool | None = None
    allow_text_output: bool = True
    profile: ReasoningLevel

    @field_validator("messages")
    @classmethod
    def _validate_messages(
        cls, value: Sequence[ChatMessageModel], info: ValidationInfo
    ) -> tuple[ChatMessageModel, ...]:
        """Require a non-empty normalized message history."""
        if len(value) == 0:
            raise ValueError(f"{info.field_name} must not be empty")
        for index, item in enumerate(value):
            prefix = f"{info.field_name}[{index}]"
            if item.role in {"system", "user"} and item.content == "":
                raise ValueError(f"{prefix}.content is required")
            if (
                item.role == "assistant"
                and item.content == ""
                and len(item.tool_calls) == 0
            ):
                raise ValueError(f"{prefix} must include content or tool_calls")
            if item.role == "assistant" and item.tool_name != "":
                raise ValueError(
                    f"{prefix}.tool_name is not valid for assistant messages"
                )
            if item.role == "assistant" and item.tool_call_id != "":
                raise ValueError(
                    f"{prefix}.tool_call_id is not valid for assistant messages"
                )
            if item.role == "tool":
                if item.tool_call_id == "":
                    raise ValueError(f"{prefix}.tool_call_id is required")
                if item.content == "":
                    raise ValueError(f"{prefix}.content is required")
                if len(item.tool_calls) != 0:
                    raise ValueError(
                        f"{prefix}.tool_calls is not valid for tool messages"
                    )
            if item.role in {"system", "user"} and len(item.tool_calls) != 0:
                raise ValueError(
                    f"{prefix}.tool_calls is only valid for assistant messages"
                )
        return tuple(value)


class EmbedRequest(_ValidationModel):
    """Validated request shape for single embedding generation."""

    text: str
    profile: EmbeddingProfile

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str, info: ValidationInfo) -> str:
        """Validate one non-empty text input."""
        return _require_text(value, field_name=info.field_name)

    @field_validator("profile")
    @classmethod
    def _validate_profile(cls, value: EmbeddingProfile) -> EmbeddingProfile:
        """Restrict single embed operation to supported embedding profiles."""
        if value not in {
            EmbeddingProfile.DOCUMENT_EMBEDDING,
            EmbeddingProfile.CAPABILITY_EMBEDDING,
        }:
            raise ValueError(
                "profile must be document_embedding or capability_embedding"
            )
        return value


class EmbedBatchRequest(_ValidationModel):
    """Validated request shape for batch embedding generation."""

    texts: tuple[str, ...]
    profile: EmbeddingProfile

    @field_validator("texts")
    @classmethod
    def _validate_texts(
        cls, value: Sequence[str], info: ValidationInfo
    ) -> tuple[str, ...]:
        """Validate one non-empty text list."""
        return _require_text_items(value, field_name=info.field_name)

    @field_validator("profile")
    @classmethod
    def _validate_profile(cls, value: EmbeddingProfile) -> EmbeddingProfile:
        """Restrict batch embed operation to supported embedding profiles."""
        if value not in {
            EmbeddingProfile.DOCUMENT_EMBEDDING,
            EmbeddingProfile.CAPABILITY_EMBEDDING,
        }:
            raise ValueError(
                "profile must be document_embedding or capability_embedding"
            )
        return value
