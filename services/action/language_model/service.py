"""Authoritative in-process Python API for Language Model Service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from resources.adapters.llm.adapter import LlmAdapter
from services.action.language_model.domain import (
    ChatResponse,
    ChatWithToolsResponse,
    EmbeddingVector,
    HealthStatus,
    InferenceRequest,
)
from services.action.language_model.validation import EmbeddingProfile, ReasoningLevel


class LanguageModelService(ABC):
    """Public API for chat and embedding operations."""

    @abstractmethod
    def chat(
        self,
        *,
        meta: EnvelopeMeta,
        system_prompt: str = "",
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
    def chat_with_tools(
        self,
        *,
        meta: EnvelopeMeta,
        inference_request: InferenceRequest,
    ) -> Envelope[ChatWithToolsResponse]:
        """Generate one tool-capable chat completion."""

    @abstractmethod
    def embed(
        self,
        *,
        meta: EnvelopeMeta,
        text: str,
        profile: EmbeddingProfile = EmbeddingProfile.DOCUMENT_EMBEDDING,
    ) -> Envelope[EmbeddingVector]:
        """Generate one embedding vector."""

    @abstractmethod
    def embed_batch(
        self,
        *,
        meta: EnvelopeMeta,
        texts: Sequence[str],
        profile: EmbeddingProfile = EmbeddingProfile.DOCUMENT_EMBEDDING,
    ) -> Envelope[list[EmbeddingVector]]:
        """Generate a batch of embedding vectors."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return LMS and adapter health state."""


def build_language_model_service(
    *,
    settings: CoreRuntimeSettings,
    adapter: LlmAdapter | None = None,
) -> LanguageModelService:
    """Build default Language Model implementation from typed settings."""
    from resources.adapters.llm import (
        HttpLlmAdapter,
        resolve_llm_adapter_settings,
    )
    from services.action.language_model.data.repository import (
        PostgresLanguageModelCallAuditRepository,
        PostgresLanguageModelTurnCacheHopRepository,
    )
    from services.action.language_model.data.runtime import LanguageModelPostgresRuntime
    from services.action.language_model.config import (
        resolve_language_model_service_settings,
    )
    from services.action.language_model.implementation import (
        DefaultLanguageModelService,
    )

    runtime = LanguageModelPostgresRuntime.from_settings(settings)
    return DefaultLanguageModelService(
        settings=resolve_language_model_service_settings(settings),
        adapter=adapter
        or HttpLlmAdapter(settings=resolve_llm_adapter_settings(settings)),
        audit_repository=PostgresLanguageModelCallAuditRepository(
            runtime.schema_sessions
        ),
        turn_cache_hop_repository=PostgresLanguageModelTurnCacheHopRepository(
            runtime.schema_sessions
        ),
    )
