"""Domain models for Language Model Service API payloads."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ChatResponse(BaseModel):
    """One generated chat completion payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    provider: str
    model: str


class ChatToolDefinition(BaseModel):
    """One tool definition passed through the tool-capable chat boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    parameters_json_schema: dict[str, object]
    description: str | None = None
    strict: bool | None = None
    sequential: bool = False


class ChatToolCall(BaseModel):
    """One normalized tool call emitted by the model or replayed in history."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str
    args_json: str
    tool_call_id: str


class ChatMessage(BaseModel):
    """One normalized chat history message for tool-capable chat."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    content: str = ""
    tool_name: str = ""
    tool_call_id: str = ""
    tool_calls: tuple[ChatToolCall, ...] = ()


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
