"""Domain models for Language Service API payloads."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatResponse(BaseModel):
    """One generated chat completion payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    provider: str
    model: str


class ChatToolCall(BaseModel):
    """One normalized tool call emitted by the model or replayed in history."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str
    args_json: str
    tool_call_id: str


class ChatWithToolsResponse(BaseModel):
    """One tool-capable chat completion payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str
    finish_reason: str
    text: str | None = None
    tool_calls: tuple[ChatToolCall, ...] = ()


class EmbeddingVector(BaseModel):
    """One embedding generation payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    values: tuple[float, ...]
    provider: str
    model: str


class HealthStatus(BaseModel):
    """Language Service and adapter readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    adapter_ready: bool
    detail: str


class TokenUsageTotals(BaseModel):
    """Aggregate token usage projection across one or more audited calls.

    Totals are derived by aggregating provider-reported usage (the
    ``response_json.usage`` block) across persisted call rows. Cache-related
    counters surface alongside raw input/output tokens so callers can reason
    about effective spend separately from the raw input prefix counted by
    providers like Anthropic.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    call_count: int = 0


class LanguageModelCallAuditRow(BaseModel):
    """One append-only Language audit row for a provider-bound call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    envelope_id: str
    trace_id: str
    parent_id: str = ""
    source: str
    principal: str
    provider: str
    model: str
    profile: str
    operation: str
    request_phase: str
    outcome_kind: str
    call_index: int
    duration_ms: float | None = None
    finish_reason: str | None = None
    error_message: str | None = None
    request_json: object | None = None
    response_json: object | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LanguageModelTurnCacheHopRow(BaseModel):
    """One append-only per-hop cache telemetry row for tool-capable Language calls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str
    hop_ordinal: int
    call_index: int
    envelope_id: str
    provider: str
    model: str
    profile: str
    placed_cachepoint_ordinal: int | None = None
    cp0_active: bool = False
    cp1_active: bool = False
    cp2_active: bool = False
    cp3_active: bool = False
    active_cachepoint_count: int = 0
    provider_cache_control_block_count: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    estimated_write_premium_token_equiv: float = 0.0
    estimated_read_savings_token_equiv: float = 0.0
    estimated_net_token_equiv: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


__all__ = [
    "ChatResponse",
    "ChatToolCall",
    "ChatWithToolsResponse",
    "EmbeddingVector",
    "HealthStatus",
    "LanguageModelCallAuditRow",
    "LanguageModelTurnCacheHopRow",
    "TokenUsageTotals",
]
