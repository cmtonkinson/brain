"""Authoritative in-process Python API for Language Model Service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from resources.adapters.litellm.adapter import LiteLlmAdapter
from services.action.language_model.domain import (
    ChatResponse,
    EmbeddingVector,
    HealthStatus,
)
from services.action.language_model.validation import EmbeddingProfile, ReasoningLevel


class LanguageModelService(ABC):
    """Public API for chat and embedding operations."""

    @abstractmethod
    def chat(
        self,
        *,
        meta: EnvelopeMeta,
        prompt: str,
        profile: ReasoningLevel = ReasoningLevel.STANDARD,
    ) -> Envelope[ChatResponse]:
        """Generate one chat completion."""

    @abstractmethod
    def chat_batch(
        self,
        *,
        meta: EnvelopeMeta,
        prompts: Sequence[str],
        profile: ReasoningLevel = ReasoningLevel.STANDARD,
    ) -> Envelope[list[ChatResponse]]:
        """Generate a batch of chat completions."""

    @abstractmethod
    def embed(
        self,
        *,
        meta: EnvelopeMeta,
        text: str,
        profile: EmbeddingProfile = EmbeddingProfile.EMBEDDING,
    ) -> Envelope[EmbeddingVector]:
        """Generate one embedding vector."""

    @abstractmethod
    def embed_batch(
        self,
        *,
        meta: EnvelopeMeta,
        texts: Sequence[str],
        profile: EmbeddingProfile = EmbeddingProfile.EMBEDDING,
    ) -> Envelope[list[EmbeddingVector]]:
        """Generate a batch of embedding vectors."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return LMS and adapter health state."""


def build_language_model_service(
    *,
    settings: BrainSettings,
    adapter: LiteLlmAdapter | None = None,
) -> LanguageModelService:
    """Build default Language Model implementation from typed settings."""
    from resources.adapters.litellm import (
        LiteLlmLibraryAdapter,
        resolve_litellm_adapter_settings,
    )
    from services.action.language_model.config import (
        resolve_language_model_service_settings,
    )
    from services.action.language_model.implementation import (
        DefaultLanguageModelService,
    )

    return DefaultLanguageModelService(
        settings=resolve_language_model_service_settings(settings),
        adapter=adapter
        or LiteLlmLibraryAdapter(settings=resolve_litellm_adapter_settings(settings)),
    )
