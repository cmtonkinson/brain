"""Authoritative in-process Python API for Capability Engine Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from services.action.capability_engine.domain import (
    CapabilityEngineHealthStatus,
    CapabilityInvocationMetadata,
    CapabilityInvokeResult,
)


class CapabilityEngineService(ABC):
    """Public API for capability invocation under policy governance."""

    @abstractmethod
    def invoke_capability(
        self,
        *,
        meta: EnvelopeMeta,
        capability_id: str,
        input_payload: dict[str, object],
        invocation: CapabilityInvocationMetadata,
    ) -> Envelope[CapabilityInvokeResult]:
        """Invoke one capability package by ``capability_id``."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[CapabilityEngineHealthStatus]:
        """Return CES readiness, registry counts, and invocation-audit counters."""
