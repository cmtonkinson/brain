"""Domain models for Language Model Service API payloads."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ChatResponse(BaseModel):
    """One generated chat completion payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    provider: str
    model: str


class EmbeddingVector(BaseModel):
    """One embedding generation payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    values: tuple[float, ...]
    provider: str
    model: str


class HealthStatus(BaseModel):
    """Language Model Service and adapter readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    adapter_ready: bool
    detail: str
