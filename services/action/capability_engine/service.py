"""Authoritative in-process Python API for Capability Engine Service."""

from __future__ import annotations

from abc import ABC, abstractmethod
import json

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from resources.adapters.utcp_code_mode.adapter import UtcpCodeModeAdapter
from services.action.language_model.service import LanguageModelService
from services.action.policy_service.service import PolicyService
from services.action.capability_engine.domain import (
    CapabilityDescriptor,
    CapabilityEngineHealthStatus,
    CapabilityInvocationMetadata,
    CapabilityInvokeResult,
    CapabilitySearchHit,
)
from services.state.embedding_authority.service import EmbeddingAuthorityService


class CapabilityEngineService(ABC):
    """Public API for capability invocation under policy governance."""

    @abstractmethod
    def describe_capabilities(
        self, *, meta: EnvelopeMeta
    ) -> Envelope[tuple[CapabilityDescriptor, ...]]:
        """Return descriptors for all registered capabilities.

        Provides everything an L2 agent needs to present capabilities as LLM
        tool calls and then invoke them via ``invoke_capability``.
        """

    @abstractmethod
    def list_always_on_capabilities(
        self, *, meta: EnvelopeMeta
    ) -> Envelope[tuple[CapabilityDescriptor, ...]]:
        """Return full descriptors for only the configured always-on capabilities."""

    @abstractmethod
    def search_capabilities(
        self,
        *,
        meta: EnvelopeMeta,
        query: str,
        limit: int | None = None,
    ) -> Envelope[tuple[CapabilitySearchHit, ...]]:
        """Return compact top-k semantic matches from the capability catalog."""

    @abstractmethod
    def describe_capability(
        self,
        *,
        meta: EnvelopeMeta,
        capability_id: str,
    ) -> Envelope[CapabilityDescriptor]:
        """Return the full descriptor for one registered capability."""

    @abstractmethod
    def resolve_slash_command(
        self,
        *,
        meta: EnvelopeMeta,
        name: str,
    ) -> Envelope[CapabilityDescriptor | None]:
        """Return the descriptor for a slash command by name or alias.

        Returns ``None`` payload when no capability is bound to the given name.
        """

    @abstractmethod
    def invoke_capability(
        self,
        *,
        meta: EnvelopeMeta,
        capability_id: str,
        input_payload: dict[str, object],
        invocation: CapabilityInvocationMetadata,
    ) -> Envelope[CapabilityInvokeResult]:
        """Invoke by package ``capability_id`` (no version arg) and return normalized policy fields."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[CapabilityEngineHealthStatus]:
        """Return CES readiness, registry counts, and invocation-audit counters."""


def build_capability_engine_service(
    *,
    settings: CoreRuntimeSettings,
    policy_service: PolicyService,
    language_model_service: LanguageModelService,
    embedding_authority_service: EmbeddingAuthorityService,
    code_mode_adapter: UtcpCodeModeAdapter | None = None,
) -> CapabilityEngineService:
    """Build default Capability Engine implementation from typed settings."""
    from resources.adapters.utcp_code_mode import (
        LocalFileUtcpCodeModeAdapter,
        resolve_utcp_code_mode_adapter_settings,
    )
    from services.action.capability_engine.config import (
        resolve_capability_engine_settings,
    )
    from services.action.capability_engine.implementation import (
        DefaultCapabilityEngineService,
    )
    from services.action.capability_engine.data.repository import (
        PostgresCapabilityDiscoveryStateRepository,
        PostgresCapabilityInvocationAuditRepository,
    )
    from services.action.capability_engine.data.runtime import (
        CapabilityEnginePostgresRuntime,
    )
    from services.action.capability_engine.registry import CapabilityRegistry

    resolved = resolve_capability_engine_settings(settings)
    registry = CapabilityRegistry()
    active_adapter = code_mode_adapter or LocalFileUtcpCodeModeAdapter(
        settings=resolve_utcp_code_mode_adapter_settings(settings)
    )
    code_mode_config = active_adapter.load()
    runtime = CapabilityEnginePostgresRuntime.from_settings(settings)
    return DefaultCapabilityEngineService(
        settings=resolved,
        policy_service=policy_service,
        language_model_service=language_model_service,
        embedding_authority_service=embedding_authority_service,
        registry=registry,
        code_mode_adapter=active_adapter,
        code_mode_config=code_mode_config,
        audit_repository=PostgresCapabilityInvocationAuditRepository(
            runtime.schema_sessions
        ),
        discovery_state_repository=PostgresCapabilityDiscoveryStateRepository(
            runtime.schema_sessions
        ),
        capability_embedding_profile_fingerprint=_capability_embedding_profile_fingerprint(
            settings
        ),
    )


def _capability_embedding_profile_fingerprint(settings: CoreRuntimeSettings) -> str:
    """Read the capability-embedding profile fingerprint from root settings only."""
    service_settings = settings.core.service.model_dump(mode="python")
    language_model = service_settings.get("language_model", {})
    if not isinstance(language_model, dict):
        return ""
    capability_embedding = language_model.get("capability_embedding", {})
    if not isinstance(capability_embedding, dict):
        return ""
    provider = str(capability_embedding.get("provider", "")).strip()
    model = str(capability_embedding.get("model", "")).strip()
    dimensions = int(capability_embedding.get("dimensions", 0) or 0)
    return json.dumps(
        {
            "provider": provider,
            "model": model,
            "dimensions": dimensions,
        },
        sort_keys=True,
    )
