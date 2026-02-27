"""Authoritative in-process Python API for Policy Service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from services.action.attention_router.service import AttentionRouterService
from services.action.policy_service.domain import (
    CapabilityInvocationRequest,
    PolicyExecutionResult,
    PolicyHealthStatus,
)

PolicyExecuteCallback = Callable[[CapabilityInvocationRequest], PolicyExecutionResult]


class PolicyService(ABC):
    """Public API for policy evaluation and callback-gated authorization."""

    @abstractmethod
    def authorize_and_execute(
        self,
        *,
        request: CapabilityInvocationRequest,
        execute: PolicyExecuteCallback,
    ) -> PolicyExecutionResult:
        """Return PolicyExecutionResult with allow/deny output, PolicyDecision, and ApprovalProposal."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[PolicyHealthStatus]:
        """Return Policy Service readiness and persistence-backed audit counters."""


def build_policy_service(
    *,
    settings: CoreRuntimeSettings,
    attention_router_service: AttentionRouterService | None = None,
) -> PolicyService:
    """Build default Policy Service implementation from typed settings."""
    from services.action.policy_service.implementation import DefaultPolicyService

    return DefaultPolicyService.from_settings(
        settings=settings,
        attention_router_service=attention_router_service,
    )
