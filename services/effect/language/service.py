"""Authoritative in-process Python API for Language Service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from resources.adapters.llm.adapter import LlmAdapter
from lib.shared.language_model import InferenceRequest
from services.effect.language.domain import (
    ChatResponse,
    ChatWithToolsResponse,
    EmbeddingVector,
    HealthStatus,
    TokenUsageTotals,
)
from services.effect.language.validation import EmbeddingProfile, ReasoningLevel


class LanguageService(ABC):
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
    def get_token_usage_by_trace(
        self,
        *,
        meta: EnvelopeMeta,
        trace_id: str,
    ) -> Envelope[TokenUsageTotals]:
        """Return aggregate token totals across all successful audited calls
        sharing one ``trace_id``.

        Used by other services (notably Delegation) to enforce per-invocation
        token budgets without re-counting tokens client-side. The totals are
        derived from persisted provider responses in ``call_audits``.
        """

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Language and adapter health state."""


def build_language_service(
    *,
    settings: CoreRuntimeSettings,
    adapter: LlmAdapter | None = None,
) -> LanguageService:
    """Build default Language implementation from typed settings."""
    from resources.adapters.llm import (
        HttpLlmAdapter,
        resolve_llm_adapter_settings,
    )
    from services.effect.language.data.repository import (
        PostgresLanguageModelCallAuditRepository,
        PostgresLanguageModelTurnCacheHopRepository,
    )
    from services.effect.language.data.runtime import LanguagePostgresRuntime
    from services.effect.language.config import (
        resolve_language_service_settings,
    )
    from services.effect.language.implementation import (
        DefaultLanguageService,
    )

    runtime = LanguagePostgresRuntime.from_settings(settings)
    return DefaultLanguageService(
        settings=resolve_language_service_settings(settings),
        adapter=adapter
        or HttpLlmAdapter(settings=resolve_llm_adapter_settings(settings)),
        audit_repository=PostgresLanguageModelCallAuditRepository(
            runtime.schema_sessions
        ),
        turn_cache_hop_repository=PostgresLanguageModelTurnCacheHopRepository(
            runtime.schema_sessions
        ),
    )
