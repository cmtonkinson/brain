"""Domain contracts for Capability Engine Service invocation APIs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from services.action.policy_service.domain import PolicyDecision


class CapabilityIdentity(BaseModel):
    """Capability identity requested by CES callers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["skill", "op"]
    namespace: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = ""


class CapabilityPolicyContext(BaseModel):
    """Policy context supplied with one capability invocation request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    allowed_capabilities: tuple[str, ...] = ()
    max_autonomy: int | None = None
    confirmed: bool = False
    approval_token: str = ""
    invocation_id: str = Field(min_length=1)
    parent_invocation_id: str = ""


class CapabilityInvokeResult(BaseModel):
    """Output payload returned by CES invoke operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str
    output: dict[str, Any] | None = None
    policy_decision_id: str
    policy_allowed: bool
    policy_reason_codes: tuple[str, ...]
    proposal_id: str = ""


class CapabilityEngineHealthStatus(BaseModel):
    """Capability Engine health payload and registry counters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    policy_ready: bool
    discovered_capabilities: int
    detail: str


class CapabilityExecutionResponse(BaseModel):
    """Internal execution result type used by policy callback wrappers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output: dict[str, Any] | None = None


class CapabilitySpec(BaseModel):
    """Loaded capability declaration with execution policy metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["skill", "op"]
    namespace: str
    name: str
    version: str
    autonomy: int = 0
    requires_approval: bool = False

    @property
    def capability_id(self) -> str:
        """Return stable capability-id string used by policy checks."""
        version = self.version or "latest"
        return f"{self.kind}:{self.namespace}:{self.name}:{version}"


class CapabilityPolicySummary(BaseModel):
    """Policy-decision summary included in CES successful responses."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: PolicyDecision
    proposal_id: str = ""
