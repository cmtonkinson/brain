"""Domain contracts for Cache Authority Service payloads."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue


class CacheEntry(BaseModel):
    """One component-scoped cache value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component_id: str
    key: str
    value: JsonValue
    ttl_seconds: int | None


class QueueEntry(BaseModel):
    """One component-scoped queue value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component_id: str
    queue: str
    value: JsonValue


class QueueDepth(BaseModel):
    """Queue depth snapshot after a push operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component_id: str
    queue: str
    size: int


class HealthStatus(BaseModel):
    """CAS and Redis readiness status payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    substrate_ready: bool
    detail: str
