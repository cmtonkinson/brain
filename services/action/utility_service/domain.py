"""Domain models for Utility Service API payloads."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TextChunk(BaseModel):
    """One utility-produced text chunk."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_ordinal: int
    text: str
    reference_range: str


class CurrentDateTime(BaseModel):
    """Operator-aware current datetime payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    utc_timestamp: str
    local_timestamp: str
    local_timezone: str


class HealthStatus(BaseModel):
    """Utility Service readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    detail: str
