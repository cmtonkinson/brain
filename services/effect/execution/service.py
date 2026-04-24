"""Authoritative in-process Python API for Execution Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from services.effect.language.service import LanguageService
from services.reason.policy.service import PolicyService
from services.effect.execution.domain import (
    DynamicOpClassificationRow,
    OpDescriptor,
    ExecutionHealthStatus,
    OpInvocationMetadata,
    OpInvokeResult,
    OpSearchHit,
    ToolSystemHint,
)
from services.state.embedding.service import EmbeddingService


class ExecutionService(ABC):
    """Public API for op invocation under policy governance."""

    @abstractmethod
    def describe_ops(self, *, meta: EnvelopeMeta) -> Envelope[tuple[OpDescriptor, ...]]:
        """Return descriptors for all registered ops.

        Provides everything a Tier 3 agent needs to present ops as LLM
        tool calls and then invoke them via ``invoke_op``.
        """

    @abstractmethod
    def list_always_on_ops(
        self, *, meta: EnvelopeMeta
    ) -> Envelope[tuple[OpDescriptor, ...]]:
        """Return full descriptors for only the configured always-on ops."""

    @abstractmethod
    def search_ops(
        self,
        *,
        meta: EnvelopeMeta,
        query: str,
        limit: int | None = None,
    ) -> Envelope[tuple[OpSearchHit, ...]]:
        """Return compact top-k semantic matches from the op catalog."""

    @abstractmethod
    def list_tool_system_hints(
        self, *, meta: EnvelopeMeta
    ) -> Envelope[tuple[ToolSystemHint, ...]]:
        """Return compact orientation hints for systems reachable through tools."""

    @abstractmethod
    def describe_op(
        self,
        *,
        meta: EnvelopeMeta,
        op_id: str,
    ) -> Envelope[OpDescriptor]:
        """Return the full descriptor for one registered op."""

    @abstractmethod
    def resolve_slash_command(
        self,
        *,
        meta: EnvelopeMeta,
        name: str,
    ) -> Envelope[OpDescriptor | None]:
        """Return the descriptor for a slash command by name or alias.

        Returns ``None`` payload when no op is bound to the given name.
        """

    @abstractmethod
    def list_dynamic_op_classifications(
        self, *, meta: EnvelopeMeta
    ) -> Envelope[tuple[DynamicOpClassificationRow, ...]]:
        """Return observed dynamic op definitions and persisted classifications."""

    @abstractmethod
    def classify_dynamic_op(
        self,
        *,
        meta: EnvelopeMeta,
        op_id: str,
        effect: str | None = None,
        approval: str | None = None,
    ) -> Envelope[DynamicOpClassificationRow]:
        """Persist one operator-supplied classification for a dynamic op.

        Either ``effect`` or ``approval`` may be omitted to leave the existing
        persisted value unchanged.
        """

    @abstractmethod
    def invoke_op(
        self,
        *,
        meta: EnvelopeMeta,
        op_id: str,
        input_payload: dict[str, object],
        invocation: OpInvocationMetadata,
    ) -> Envelope[OpInvokeResult]:
        """Invoke by package ``op_id`` (no version arg) and return normalized policy fields."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[ExecutionHealthStatus]:
        """Return Execution readiness, registry counts, and invocation-audit counters."""


def build_execution_service(
    *,
    settings: CoreRuntimeSettings,
    policy_service: PolicyService,
    language_service: LanguageService,
    embedding_service: EmbeddingService,
    mcp_adapter: object | None = None,
) -> ExecutionService:
    """Build default Execution implementation from typed settings."""
    from services.effect.execution.config import (
        resolve_execution_settings,
    )
    from services.effect.execution.implementation import (
        DefaultExecutionService,
        _resolve_op_embedding_profile_fingerprint,
    )
    from services.effect.execution.data.repository import (
        PostgresDynamicOpClassificationRepository,
        PostgresOpDiscoveryStateRepository,
        PostgresOpInvocationAuditRepository,
    )
    from services.effect.execution.data.runtime import (
        ExecutionPostgresRuntime,
    )
    from services.effect.execution.registry import OpRegistry

    resolved = resolve_execution_settings(settings)
    registry = OpRegistry()
    runtime = ExecutionPostgresRuntime.from_settings(settings)
    return DefaultExecutionService(
        settings=resolved,
        policy_service=policy_service,
        language_service=language_service,
        embedding_service=embedding_service,
        registry=registry,
        mcp_adapter=mcp_adapter,
        audit_repository=PostgresOpInvocationAuditRepository(runtime.schema_sessions),
        discovery_state_repository=PostgresOpDiscoveryStateRepository(
            runtime.schema_sessions
        ),
        dynamic_op_classification_repository=PostgresDynamicOpClassificationRepository(
            runtime.schema_sessions
        ),
        op_embedding_profile_fingerprint=_resolve_op_embedding_profile_fingerprint(
            settings
        ),
    )
