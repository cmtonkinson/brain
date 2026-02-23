"""Authoritative in-process Python API for Language Model Service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from services.action.language_model.domain import (
    ChatResponse,
    EmbeddingVector,
    HealthStatus,
)
from services.action.language_model.validation import ModelProfile


class LanguageModelService(ABC):
    """Public API for chat and embedding operations."""

    @abstractmethod
    def chat(
        self,
        *,
        meta: EnvelopeMeta,
        prompt: str,
        profile: ModelProfile = ModelProfile.CHAT_DEFAULT,
    ) -> Envelope[ChatResponse]:
        """Generate one chat completion."""

    @abstractmethod
    def chat_batch(
        self,
        *,
        meta: EnvelopeMeta,
        prompts: Sequence[str],
        profile: ModelProfile = ModelProfile.CHAT_DEFAULT,
    ) -> Envelope[list[ChatResponse]]:
        """Generate a batch of chat completions."""

    @abstractmethod
    def embed(
        self,
        *,
        meta: EnvelopeMeta,
        text: str,
        profile: ModelProfile = ModelProfile.EMBEDDING,
    ) -> Envelope[EmbeddingVector]:
        """Generate one embedding vector."""

    @abstractmethod
    def embed_batch(
        self,
        *,
        meta: EnvelopeMeta,
        texts: Sequence[str],
        profile: ModelProfile = ModelProfile.EMBEDDING,
    ) -> Envelope[list[EmbeddingVector]]:
        """Generate a batch of embedding vectors."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return LMS and adapter health state."""
