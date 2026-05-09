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


class ParsedDateTime(BaseModel):
    """Parsed datetime with UTC and requested-local projections."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_timestamp: str
    local_timestamp: str
    local_timezone: str
    utc_timestamp: str
    unix_timestamp: float


class ConvertedDateTime(BaseModel):
    """Datetime converted from one timezone to another."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_timestamp: str
    from_timezone: str
    to_timezone: str
    converted_timestamp: str
    utc_timestamp: str
    unix_timestamp: float


class DurationUntil(BaseModel):
    """Signed duration from one instant to a target instant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    now_timestamp: str
    target_timestamp: str
    seconds: float
    minutes: float
    hours: float
    days: float
    is_past: bool


class HealthStatus(BaseModel):
    """Utility Service readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    detail: str
