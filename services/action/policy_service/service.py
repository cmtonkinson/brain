"""Authoritative in-process Python API for Policy Service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from packages.brain_shared.envelope import Envelope, EnvelopeMeta
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
        """Evaluate one invocation, returning normalized decision/approval metadata."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[PolicyHealthStatus]:
        """Return Policy Service readiness and in-memory audit counters."""
