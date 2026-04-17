"""Domain models for Language Model Service API payloads."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.language_model import InferenceRequest


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
    """Language Model Service and adapter readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    adapter_ready: bool
    detail: str


class ProviderCallAudit(BaseModel):
    """Raw provider request/response artifacts captured at the adapter boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_api_base: str = ""
    request_headers: dict[str, object] = Field(default_factory=dict)
    request_body: object | None = None
    response_body: object | None = None


class LanguageModelCallAuditRow(BaseModel):
    """One append-only LMS audit row for a provider-bound call."""

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
    finish_reason: str = ""
    error_message: str = ""
    request_json: object | None = None
    response_json: object | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LanguageModelTurnCacheHopRow(BaseModel):
    """One append-only per-hop cache telemetry row for tool-capable LMS calls."""

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
    "InferenceRequest",
    "LanguageModelCallAuditRow",
    "LanguageModelTurnCacheHopRow",
    "ProviderCallAudit",
]
