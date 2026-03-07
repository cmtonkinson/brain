"""Transport-agnostic LiteLLM adapter contract and DTOs."""

from __future__ import annotations

from typing import Protocol, Sequence

from pydantic import BaseModel, ConfigDict


class AdapterError(Exception):
    """Base exception for adapter-level failures."""


class AdapterDependencyError(AdapterError):
    """Dependency-level adapter failure (network, upstream, timeout)."""


class AdapterInternalError(AdapterError):
    """Internal adapter failure (malformed response, mapping bug)."""


class AdapterChatResult(BaseModel):
    """Adapter response payload for one chat completion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    provider: str
    model: str


class AdapterChatToolDefinition(BaseModel):
    """One normalized tool definition passed to LiteLLM."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    parameters_json_schema: dict[str, object]
    description: str | None = None
    strict: bool | None = None
    sequential: bool = False


class AdapterChatToolCall(BaseModel):
    """One normalized tool call returned by LiteLLM."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str
    args_json: str
    tool_call_id: str


class AdapterChatMessage(BaseModel):
    """One normalized chat history message passed through LiteLLM."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    content: str = ""
    tool_name: str = ""
    tool_call_id: str = ""
    tool_calls: tuple[AdapterChatToolCall, ...] = ()


class AdapterToolChatResult(BaseModel):
    """One normalized tool-capable completion returned by LiteLLM."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str | None = None
    tool_calls: tuple[AdapterChatToolCall, ...] = ()
    provider: str
    model: str
    finish_reason: str


class AdapterEmbeddingResult(BaseModel):
    """Adapter response payload for one embedding generation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    values: tuple[float, ...]
    provider: str
    model: str


class AdapterHealthResult(BaseModel):
    """Adapter readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_ready: bool
    detail: str


class LiteLlmAdapter(Protocol):
    """Protocol for LiteLLM-backed chat and embedding operations."""

    def chat(
        self,
        *,
        provider: str,
        model: str,
        prompt: str,
    ) -> AdapterChatResult:
        """Generate one chat completion."""

    def chat_batch(
        self,
        *,
        provider: str,
        model: str,
        prompts: Sequence[str],
    ) -> list[AdapterChatResult]:
        """Generate chat completions for one batch."""

    def chat_with_tools(
        self,
        *,
        provider: str,
        model: str,
        messages: Sequence[AdapterChatMessage],
        tools: Sequence[AdapterChatToolDefinition],
        tool_choice: str | dict[str, object] | None = None,
        parallel_tool_calls: bool | None = None,
    ) -> AdapterToolChatResult:
        """Generate one tool-capable chat completion."""

    def embed(
        self,
        *,
        provider: str,
        model: str,
        text: str,
    ) -> AdapterEmbeddingResult:
        """Generate one embedding vector."""

    def embed_batch(
        self,
        *,
        provider: str,
        model: str,
        texts: Sequence[str],
    ) -> list[AdapterEmbeddingResult]:
        """Generate embedding vectors for one batch."""

    def health(self) -> AdapterHealthResult:
        """Return adapter health state."""
