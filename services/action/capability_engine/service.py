"""Authoritative in-process Python API for Capability Engine Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from resources.adapters.utcp_code_mode.adapter import UtcpCodeModeAdapter
from services.action.policy_service.service import PolicyService
from services.action.capability_engine.domain import (
    CapabilityDescriptor,
    CapabilityEngineHealthStatus,
    CapabilityInvocationMetadata,
    CapabilityInvokeResult,
)


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
    settings: BrainSettings,
    policy_service: PolicyService,
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
        registry=registry,
        code_mode_adapter=active_adapter,
        code_mode_config=code_mode_config,
        audit_repository=PostgresCapabilityInvocationAuditRepository(
            runtime.schema_sessions
        ),
    )
