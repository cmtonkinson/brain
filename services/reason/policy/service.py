"""Authoritative in-process Python API for Policy Service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from services.effect.relay.service import RelayService
from services.reason.policy.domain import (
    OpInvocationRequest,
    PolicyExecutionResult,
    PolicyHealthStatus,
)

PolicyExecuteCallback = Callable[[OpInvocationRequest], PolicyExecutionResult]


class PolicyService(ABC):
    """Public API for policy evaluation and callback-gated authorization."""

    @abstractmethod
    def authorize_and_execute(
        self,
        *,
        request: OpInvocationRequest,
        execute: PolicyExecuteCallback,
    ) -> PolicyExecutionResult:
        """Return PolicyExecutionResult with allow/deny output, PolicyDecision, and ApprovalProposal."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[PolicyHealthStatus]:
        """Return Policy Service readiness and persistence-backed audit counters."""


def build_policy_service(
    *,
    settings: CoreRuntimeSettings,
    outbound_service: RelayService | None = None,
) -> PolicyService:
    """Build default Policy Service implementation from typed settings."""
    from services.reason.policy.implementation import DefaultPolicyService

    return DefaultPolicyService.from_settings(
        settings=settings,
        outbound_service=outbound_service,
    )
