"""Authoritative in-process Python API for Capability Engine Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from services.action.capability_engine.domain import (
    CapabilityEngineHealthStatus,
    CapabilityIdentity,
    CapabilityInvokeResult,
    CapabilityPolicyContext,
)


class CapabilityEngineService(ABC):
    """Public API for capability invocation under policy governance."""

    @abstractmethod
    def invoke_capability(
        self,
        *,
        meta: EnvelopeMeta,
        capability: CapabilityIdentity,
        input_payload: dict[str, object],
        policy_context: CapabilityPolicyContext,
    ) -> Envelope[CapabilityInvokeResult]:
        """Invoke one capability via Policy Service authorization wrapper."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[CapabilityEngineHealthStatus]:
        """Return CES readiness and capability discovery counters."""
