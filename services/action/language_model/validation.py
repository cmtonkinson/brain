"""Pydantic ingress validation models for Language Model Service."""

from __future__ import annotations

from enum import StrEnum
from typing import Sequence

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator


class ReasoningLevel(StrEnum):
    """Supported chat reasoning selectors."""

    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


class EmbeddingProfile(StrEnum):
    """Supported embedding profile selectors."""

    EMBEDDING = "embedding"


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

    prompt: str
    profile: ReasoningLevel

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
        """Restrict single embed operation to embedding profile."""
        if value is not EmbeddingProfile.EMBEDDING:
            raise ValueError("profile must be embedding")
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
        """Restrict batch embed operation to embedding profile."""
        if value is not EmbeddingProfile.EMBEDDING:
            raise ValueError("profile must be embedding")
        return value
