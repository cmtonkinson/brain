"""Unit tests for the native LLM adapter."""

from __future__ import annotations

import httpx
import pytest

import resources.adapters.llm.llm_adapter as adapter_module
from lib.shared.language_model import (
    InferenceEnvironmentContext,
    InferenceEnvironmentItem,
    InferenceAssistantTextEvent,
    InferenceCache,
    InferenceMemoryContext,
    InferenceMemoryTurn,
    InferenceSystemBlock,
    InferenceToolCall,
    InferenceToolCallBatchEvent,
    InferenceToolDefinition,
    InferenceToolResult,
    InferenceToolResultBatchEvent,
    InferenceToolResultPayload,
)
from resources.adapters.llm.adapter import (
    AdapterDependencyError,
    AdapterInternalError,
)
from resources.adapters.llm.config import LlmAdapterSettings, LlmProviderSettings
from resources.adapters.llm.llm_adapter import HttpLlmAdapter
from tests.helpers.inference_request import make_inference_request


def _anthropic_settings(**provider_overrides: object) -> LlmAdapterSettings:
    """Build deterministic adapter settings for Anthropic tests."""
    provider = LlmProviderSettings(
        api_base="https://api.anthropic.com",
        options={"temperature": 0.1},
        **provider_overrides,
    )
    return LlmAdapterSettings(
        timeout_seconds=9.0,
        max_retries=1,
        retry_attempts=1,
        providers={"anthropic": provider},
    )


def _ollama_settings(**provider_overrides: object) -> LlmAdapterSettings:
    """Build deterministic adapter settings for Ollama embedding tests."""
    provider = LlmProviderSettings(
        api_base="http://localhost:11434",
        **provider_overrides,
    )
    return LlmAdapterSettings(
        timeout_seconds=9.0,
        max_retries=1,
        retry_attempts=1,
        providers={"ollama": provider},
    )


def _voyage_settings(**provider_overrides: object) -> LlmAdapterSettings:
    """Build deterministic adapter settings for Voyage embedding tests."""
    provider = LlmProviderSettings(
        api_base="https://api.voyageai.com",
        options={"output_dimension": 2048},
        **provider_overrides,
    )
    return LlmAdapterSettings(
        timeout_seconds=9.0,
        max_retries=1,
        retry_attempts=1,
        providers={"voyage": provider},
    )


def _tool_inference_request() -> object:
    """Build one canonical tool-capable inference request."""
    return make_inference_request(
        system_blocks=(
            InferenceSystemBlock(
                kind="assistant_persona",
                text="Static context",
                cache_after=True,
            ),
        ),
        memory_context=InferenceMemoryContext(
            current_focus="Current focus",
            recent_conversation_summary="Conversation summary",
            recent_turns=(
                InferenceMemoryTurn(role="user", text="Hi", is_summary=False),
                InferenceMemoryTurn(
                    role="assistant",
                    text="Hey there, how can I help?",
                    is_summary=False,
                ),
            ),
            reference_snippets=(),
        ),
        live_events=(
            InferenceAssistantTextEvent(text="Checking"),
            InferenceToolCallBatchEvent(
                calls=(
                    InferenceToolCall(
                        call_id="call-1",
                        tool_name="search_tools",
                        arguments={"query": "resume"},
                    ),
                )
            ),
            InferenceToolResultBatchEvent(
                results=(
                    InferenceToolResult(
                        call_id="call-1",
                        tool_name="search_tools",
                        result=InferenceToolResultPayload(
                            mime_type="text/plain",
                            text="search results",
                        ),
                    ),
                )
            ),
        ),
        tools=(
            InferenceToolDefinition(
                name="search_tools",
                description="Search documents.",
                input_schema={"type": "object"},
            ),
        ),
        cache=InferenceCache(mode="explicit"),
        operator_message=make_inference_request().current_turn.operator_message.model_copy(
            update={"message_text": "Find the resume"}
        ),
    )


def _json_response(payload: object, *, status_code: int = 200) -> httpx.Response:
    """Build one JSON response with a matching request object."""
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )


def test_chat_posts_native_anthropic_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Direct chat should call Anthropic's native Messages API."""
    calls: list[dict[str, object]] = []

    def _fake_post(
        url: str, *, headers: dict[str, str], json: object, timeout: float
    ) -> httpx.Response:
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _json_response(
            {
                "content": [{"type": "text", "text": "hello"}],
                "stop_reason": "end_turn",
            }
        )

    monkeypatch.setattr(adapter_module.httpx, "post", _fake_post)
    adapter = HttpLlmAdapter(settings=_anthropic_settings(api_key="secret"))

    result = adapter.chat(
        provider="anthropic",
        model="claude-sonnet-4-5",
        system_prompt="You are helpful.",
        prompt="hi",
    )

    assert result.text == "hello"
    assert result.raw_call is not None
    assert result.raw_call.request_headers["x-api-key"] == "***"
    assert calls[0]["url"] == "https://api.anthropic.com/v1/messages"
    assert calls[0]["timeout"] == 9.0
    body = calls[0]["json"]
    assert isinstance(body, dict)
    assert body["model"] == "claude-sonnet-4-5"
    assert body["max_tokens"] == adapter_module._ANTHROPIC_DEFAULT_MAX_TOKENS
    assert body["system"] == [{"type": "text", "text": "You are helpful."}]
    assert body["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    ]


def test_chat_with_tools_uses_native_anthropic_tool_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool chat should send Anthropic-native tool_use and tool_result blocks."""
    calls: list[dict[str, object]] = []

    def _fake_post(
        url: str, *, headers: dict[str, str], json: object, timeout: float
    ) -> httpx.Response:
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _json_response(
            {
                "content": [
                    {"type": "text", "text": "Need one more check."},
                    {
                        "type": "tool_use",
                        "id": "call-2",
                        "name": "search_tools",
                        "input": {"query": "resume"},
                    },
                ],
                "stop_reason": "tool_use",
            }
        )

    monkeypatch.setattr(adapter_module.httpx, "post", _fake_post)
    adapter = HttpLlmAdapter(settings=_anthropic_settings())

    result = adapter.chat_with_tools(
        provider="anthropic",
        model="claude-sonnet-4-5",
        inference_request=_tool_inference_request(),
    )

    assert result.text == "Need one more check."
    assert result.finish_reason == "tool_call"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool_name == "search_tools"
    assert result.tool_calls[0].tool_call_id == "call-2"
    body = calls[0]["json"]
    assert isinstance(body, dict)
    assert body["tools"] == [
        {
            "name": "search_tools",
            "description": "Search documents.",
            "input_schema": {"type": "object"},
        }
    ]
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[1]["role"] == "assistant"
    assert any(item.get("type") == "tool_use" for item in messages[1]["content"])
    assert messages[2]["role"] == "user"
    assert messages[2]["content"][0]["type"] == "tool_result"


def test_chat_with_tools_serializes_environment_context_after_cachepoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment context should render after CP0 without adding cache controls."""
    calls: list[dict[str, object]] = []

    def _fake_post(
        url: str, *, headers: dict[str, str], json: object, timeout: float
    ) -> httpx.Response:
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _json_response(
            {
                "content": [{"type": "text", "text": "hello"}],
                "stop_reason": "end_turn",
            }
        )

    monkeypatch.setattr(adapter_module.httpx, "post", _fake_post)
    adapter = HttpLlmAdapter(settings=_anthropic_settings())
    inference_request = make_inference_request(
        memory_context=InferenceMemoryContext(
            current_focus="Current focus",
            recent_conversation_summary="Conversation summary",
            recent_turns=(
                InferenceMemoryTurn(role="user", text="Hi", is_summary=False),
                InferenceMemoryTurn(
                    role="assistant",
                    text="Hey there, how can I help?",
                    is_summary=False,
                ),
            ),
            reference_snippets=(),
        ),
        environment_context=InferenceEnvironmentContext(
            items=(
                InferenceEnvironmentItem(
                    op_id="current-datetime",
                    tag_name="current-datetime",
                    output={
                        "utc_timestamp": "2026-01-01T12:00:00+00:00",
                        "local_timestamp": "2026-01-01T07:00:00-05:00",
                        "local_timezone": "America/New_York",
                    },
                ),
            )
        ),
        cache=InferenceCache(mode="explicit"),
    )

    adapter.chat_with_tools(
        provider="anthropic",
        model="claude-sonnet-4-5",
        inference_request=inference_request,
    )

    body = calls[0]["json"]
    assert isinstance(body, dict)
    messages = body["messages"]
    assert isinstance(messages, list)
    context_blocks = messages[0]["content"]
    assert isinstance(context_blocks, list)
    assert len(context_blocks) == 2
    assert "cache_control" in context_blocks[0]
    assert "cache_control" not in context_blocks[1]
    assert context_blocks[0]["text"].index("<areas_of_focus>") < context_blocks[0][
        "text"
    ].index("<recent_conversation_summary>")
    assert "<environment_context>" in context_blocks[1]["text"]
    assert "<current-datetime>" in context_blocks[1]["text"]
    assert "<dialogue>" in context_blocks[1]["text"]
    assert "<operator>" in context_blocks[1]["text"]
    assert "<assistant>" in context_blocks[1]["text"]
    assert "- user:" not in context_blocks[1]["text"]
    assert '"local_timezone":"America/New_York"' in context_blocks[1]["text"]


def test_chat_with_tools_caps_anthropic_cache_control_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anthropic requests must never emit more than the provider cache-block limit."""
    calls: list[dict[str, object]] = []

    def _fake_post(
        url: str, *, headers: dict[str, str], json: object, timeout: float
    ) -> httpx.Response:
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _json_response(
            {
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
            }
        )

    monkeypatch.setattr(adapter_module.httpx, "post", _fake_post)
    adapter = HttpLlmAdapter(settings=_anthropic_settings())
    inference_request = make_inference_request(
        system_blocks=(
            InferenceSystemBlock(
                kind="assistant_persona",
                text="Static context",
                cache_after=True,
            ),
        ),
        memory_context=InferenceMemoryContext(
            current_focus="Current focus",
            recent_conversation_summary="Conversation summary",
            recent_turns=(),
            reference_snippets=(),
        ),
        live_events=(
            InferenceAssistantTextEvent(text="one", cache_after=True),
            InferenceAssistantTextEvent(text="two", cache_after=True),
            InferenceAssistantTextEvent(text="three", cache_after=True),
            InferenceAssistantTextEvent(text="four", cache_after=True),
        ),
        tools=(),
        cache=InferenceCache(mode="explicit"),
        operator_message=make_inference_request().current_turn.operator_message,
    )

    result = adapter.chat_with_tools(
        provider="anthropic",
        model="claude-sonnet-4-5",
        inference_request=inference_request,
    )

    assert result.text == "ok"
    body = calls[0]["json"]
    assert isinstance(body, dict)

    def _count_cache_controls(payload: dict[str, object]) -> int:
        count = 0
        system = payload.get("system")
        if isinstance(system, list):
            count += sum(
                1
                for item in system
                if isinstance(item, dict) and "cache_control" in item
            )
        messages = payload.get("messages")
        if isinstance(messages, list):
            for message in messages:
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                count += sum(
                    1
                    for item in content
                    if isinstance(item, dict) and "cache_control" in item
                )
        return count

    assert _count_cache_controls(body) == 4


def test_chat_retries_timeout_once_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeout retries should reuse the bounded timeout retry budget."""
    attempts = {"count": 0}

    def _fake_post(
        url: str, *, headers: dict[str, str], json: object, timeout: float
    ) -> httpx.Response:
        del url, headers, json, timeout
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ReadTimeout("timed out")
        return _json_response(
            {
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
            }
        )

    monkeypatch.setattr(adapter_module.httpx, "post", _fake_post)
    adapter = HttpLlmAdapter(settings=_anthropic_settings())

    result = adapter.chat(
        provider="anthropic",
        model="claude-sonnet-4-5",
        prompt="hi",
    )

    assert result.text == "ok"
    assert attempts["count"] == 2


def test_chat_maps_retryable_http_status_to_dependency_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retryable upstream failures should surface as dependency errors."""

    def _fake_post(
        url: str, *, headers: dict[str, str], json: object, timeout: float
    ) -> httpx.Response:
        del url, headers, json, timeout
        return _json_response(
            {"error": {"message": "rate limited"}},
            status_code=429,
        )

    monkeypatch.setattr(adapter_module.httpx, "post", _fake_post)
    adapter = HttpLlmAdapter(
        settings=_anthropic_settings(max_retries=0),
    )

    with pytest.raises(AdapterDependencyError, match="rate limited"):
        adapter.chat(provider="anthropic", model="claude-sonnet-4-5", prompt="hi")


def test_chat_fails_fast_for_unsupported_provider() -> None:
    """Unsupported providers should fail immediately at call time."""
    adapter = HttpLlmAdapter(
        settings=LlmAdapterSettings(
            providers={
                "openai": LlmProviderSettings(api_base="https://api.openai.com/v1")
            }
        )
    )

    with pytest.raises(
        AdapterInternalError,
        match="provider 'openai' is not yet implemented in adapter_llm for chat",
    ):
        adapter.chat(provider="openai", model="gpt-4.1", prompt="hi")


def test_embed_batch_fails_fast_for_unsupported_provider() -> None:
    """Unsupported embedding providers should fail immediately at call time."""
    adapter = HttpLlmAdapter(settings=_anthropic_settings())

    with pytest.raises(
        AdapterInternalError,
        match="provider 'anthropic' is not yet implemented in adapter_llm for embed_batch",
    ):
        adapter.embed_batch(
            provider="anthropic",
            model="claude-sonnet-4-5",
            texts=["hello"],
        )


def test_embed_batch_posts_native_ollama_embed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embedding batches should call Ollama's native batch embedding endpoint."""
    calls: list[dict[str, object]] = []

    def _fake_post(
        url: str, *, headers: dict[str, str], json: object, timeout: float
    ) -> httpx.Response:
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return httpx.Response(
            200,
            json={
                "model": "mxbai-embed-large",
                "embeddings": [[0.1, 0.2], [0.3, 0.4]],
            },
            request=httpx.Request("POST", "http://localhost:11434/api/embed"),
        )

    monkeypatch.setattr(adapter_module.httpx, "post", _fake_post)
    adapter = HttpLlmAdapter(settings=_ollama_settings())

    result = adapter.embed_batch(
        provider="ollama",
        model="mxbai-embed-large",
        texts=["hello", "world"],
        dimensions=1024,
    )

    assert [item.values for item in result] == [(0.1, 0.2), (0.3, 0.4)]
    assert all(item.provider == "ollama" for item in result)
    assert all(item.model == "mxbai-embed-large" for item in result)
    assert result[0].raw_call is not None
    assert calls[0]["url"] == "http://localhost:11434/api/embed"
    assert calls[0]["headers"] == {"content-type": "application/json"}
    assert calls[0]["timeout"] == 9.0
    assert calls[0]["json"] == {
        "model": "mxbai-embed-large",
        "input": ["hello", "world"],
        "dimensions": 1024,
    }


def test_embed_batch_posts_voyage_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embedding batches should call Voyage's native embeddings endpoint."""
    calls: list[dict[str, object]] = []

    def _fake_post(
        url: str, *, headers: dict[str, str], json: object, timeout: float
    ) -> httpx.Response:
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return httpx.Response(
            200,
            json={
                "model": "voyage-3-large",
                "data": [
                    {"index": 0, "embedding": [0.1, 0.2]},
                    {"index": 1, "embedding": [0.3, 0.4]},
                ],
            },
            request=httpx.Request("POST", "https://api.voyageai.com/v1/embeddings"),
        )

    monkeypatch.setattr(adapter_module.httpx, "post", _fake_post)
    adapter = HttpLlmAdapter(settings=_voyage_settings(api_key="secret"))

    result = adapter.embed_batch(
        provider="voyage",
        model="voyage-3-large",
        texts=["hello", "world"],
        dimensions=1024,
    )

    assert [item.values for item in result] == [(0.1, 0.2), (0.3, 0.4)]
    assert all(item.provider == "voyage" for item in result)
    assert all(item.model == "voyage-3-large" for item in result)
    assert result[0].raw_call is not None
    assert result[0].raw_call.request_headers["authorization"] == "***"
    assert calls[0]["url"] == "https://api.voyageai.com/v1/embeddings"
    assert calls[0]["headers"] == {
        "content-type": "application/json",
        "authorization": "Bearer secret",
    }
    assert calls[0]["timeout"] == 9.0
    assert calls[0]["json"] == {
        "model": "voyage-3-large",
        "input": ["hello", "world"],
        "input_type": "document",
        "output_dimension": 1024,
    }


def test_embed_posts_voyage_query_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single Voyage embedding calls should mark the request as a query embedding."""
    calls: list[dict[str, object]] = []

    def _fake_post(
        url: str, *, headers: dict[str, str], json: object, timeout: float
    ) -> httpx.Response:
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return httpx.Response(
            200,
            json={
                "model": "voyage-3-large",
                "data": [
                    {"index": 0, "embedding": [0.1, 0.2]},
                ],
            },
            request=httpx.Request("POST", "https://api.voyageai.com/v1/embeddings"),
        )

    monkeypatch.setattr(adapter_module.httpx, "post", _fake_post)
    adapter = HttpLlmAdapter(settings=_voyage_settings(api_key="secret"))

    result = adapter.embed(
        provider="voyage",
        model="voyage-3-large",
        text="hello",
        dimensions=1024,
    )

    assert result.values == (0.1, 0.2)
    assert calls[0]["json"] == {
        "model": "voyage-3-large",
        "input": ["hello"],
        "input_type": "query",
        "output_dimension": 1024,
    }


def test_embed_batch_accepts_single_embedding_payload_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-item embedding responses should accept Ollama's singular embedding field."""

    def _fake_post(
        url: str, *, headers: dict[str, str], json: object, timeout: float
    ) -> httpx.Response:
        del url, headers, json, timeout
        return httpx.Response(
            200,
            json={"model": "mxbai-embed-large", "embedding": [0.5, 0.6]},
            request=httpx.Request("POST", "http://localhost:11434/api/embed"),
        )

    monkeypatch.setattr(adapter_module.httpx, "post", _fake_post)
    adapter = HttpLlmAdapter(settings=_ollama_settings())

    result = adapter.embed_batch(
        provider="ollama",
        model="mxbai-embed-large",
        texts=["hello"],
    )

    assert [item.values for item in result] == [(0.5, 0.6)]


def test_health_ignores_unsupported_configured_providers() -> None:
    """Health should stay ready when only unsupported providers are configured."""
    adapter = HttpLlmAdapter(
        settings=LlmAdapterSettings(
            providers={"ollama": LlmProviderSettings(api_base="http://localhost:11434")}
        )
    )

    result = adapter.health()

    assert result.adapter_ready is True
    assert result.detail == "ok"


def test_health_reports_missing_anthropic_api_key_env() -> None:
    """Anthropic health should fail when required auth env is unresolved."""
    adapter = HttpLlmAdapter(
        settings=LlmAdapterSettings(
            providers={
                "anthropic": LlmProviderSettings(api_key_env="MISSING_ANTHROPIC_KEY")
            }
        )
    )

    result = adapter.health()

    assert result.adapter_ready is False
    assert "MISSING_ANTHROPIC_KEY" in result.detail


def test_health_reports_missing_voyage_api_key() -> None:
    """Voyage health should fail when auth is not configured."""
    adapter = HttpLlmAdapter(
        settings=LlmAdapterSettings(
            providers={
                "voyage": LlmProviderSettings(api_base="https://api.voyageai.com")
            }
        )
    )

    result = adapter.health()

    assert result.adapter_ready is False
    assert result.detail == "provider 'voyage' requires an API key"
