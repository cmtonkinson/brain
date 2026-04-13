"""Unit tests for the in-process LiteLLM adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import litellm
import pytest
from unittest.mock import MagicMock, call

import resources.adapters.litellm.litellm_adapter as adapter_module
from resources.adapters.litellm.adapter import (
    AdapterChatMessage,
    AdapterChatToolDefinition,
    AdapterDependencyError,
    AdapterInternalError,
    AdapterProviderCallAudit,
)
from resources.adapters.litellm.config import (
    LiteLlmAdapterSettings,
    LiteLlmProviderSettings,
)
from resources.adapters.litellm.litellm_adapter import LiteLlmLibraryAdapter


@dataclass
class _FakeLiteLlmModule:
    """Test double for the external `litellm` module API."""

    completion_response: object = field(
        default_factory=lambda: {"choices": [{"message": {"content": "hello"}}]}
    )
    embedding_response: object = field(
        default_factory=lambda: {"data": [{"embedding": [0.1, 0.2]}]}
    )
    completion_exception: Exception | None = None
    completion_exceptions: list[Exception] = field(default_factory=list)
    embedding_exception: Exception | None = None
    completion_calls: list[dict[str, Any]] = field(default_factory=list)
    embedding_calls: list[dict[str, Any]] = field(default_factory=list)

    def completion(self, **kwargs: Any) -> object:
        self.completion_calls.append(kwargs)
        if self.completion_exceptions:
            raise self.completion_exceptions.pop(0)
        if self.completion_exception is not None:
            raise self.completion_exception
        return self.completion_response

    def embedding(self, **kwargs: Any) -> object:
        self.embedding_calls.append(kwargs)
        if self.embedding_exception is not None:
            raise self.embedding_exception
        return self.embedding_response


def _settings() -> LiteLlmAdapterSettings:
    """Build deterministic adapter settings with one configured provider."""
    return LiteLlmAdapterSettings(
        timeout_seconds=9.0,
        max_retries=2,
        providers={
            "ollama": LiteLlmProviderSettings(
                api_base="http://localhost:11434",
                options={"temperature": 0.0},
            )
        },
    )


def test_chat_calls_litellm_completion_with_resolved_provider_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chat should compose provider/model selector and pass merged request kwargs."""
    fake_module = _FakeLiteLlmModule()
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    adapter = LiteLlmLibraryAdapter(settings=_settings())

    result = adapter.chat(provider="ollama", model="gpt-oss", prompt="hi")

    assert result.text == "hello"
    assert result.provider == "ollama"
    assert result.model == "gpt-oss"
    assert len(fake_module.completion_calls) == 1
    assert fake_module.completion_calls[0]["model"] == "ollama/gpt-oss"
    assert fake_module.completion_calls[0]["api_base"] == "http://localhost:11434"
    assert fake_module.completion_calls[0]["timeout"] == 9.0
    assert fake_module.completion_calls[0]["num_retries"] == 2
    assert fake_module.completion_calls[0]["temperature"] == 0.0
    assert callable(fake_module.completion_calls[0]["logger_fn"])
    assert fake_module.log_raw_request_response is True


def test_chat_success_audit_falls_back_to_local_request_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful chat should audit sanitized request/response without hook payloads."""
    fake_module = _FakeLiteLlmModule(
        completion_response={"choices": [{"message": {"content": "hello"}}]}
    )
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    adapter = LiteLlmLibraryAdapter(settings=_settings())

    result = adapter.chat(provider="ollama", model="gpt-oss", prompt="hi")

    assert result.raw_call == AdapterProviderCallAudit(
        request_api_base="http://localhost:11434",
        request_headers={},
        request_body={
            "model": "ollama/gpt-oss",
            "temperature": 0.0,
            "messages": [{"role": "user", "content": "hi"}],
        },
        response_body={"choices": [{"message": {"content": "hello"}}]},
    )


def test_chat_with_tools_passes_tools_and_maps_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool-capable chat should pass through tool settings and map tool calls."""
    fake_module = _FakeLiteLlmModule(
        completion_response={
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "demo-tool",
                                    "arguments": '{"value":"x"}',
                                },
                            }
                        ],
                    },
                }
            ]
        }
    )
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    adapter = LiteLlmLibraryAdapter(settings=_settings())

    result = adapter.chat_with_tools(
        provider="ollama",
        model="gpt-oss",
        messages=(AdapterChatMessage(role="user", content="hello"),),
        tools=(
            AdapterChatToolDefinition(
                name="demo-tool",
                description="Do a thing.",
                parameters_json_schema={"type": "object"},
                strict=True,
            ),
        ),
        tool_choice="auto",
        parallel_tool_calls=True,
    )

    assert result.finish_reason == "tool_call"
    assert result.tool_calls[0].tool_name == "demo-tool"
    assert fake_module.completion_calls[0]["tool_choice"] == "auto"
    assert fake_module.completion_calls[0]["parallel_tool_calls"] is True
    assert callable(fake_module.completion_calls[0]["logger_fn"])
    assert fake_module.completion_calls[0]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "demo-tool",
                "description": "Do a thing.",
                "parameters": {"type": "object"},
                "strict": True,
            },
        }
    ]
    assert result.raw_call == AdapterProviderCallAudit(
        request_api_base="http://localhost:11434",
        request_headers={},
        request_body={
            "model": "ollama/gpt-oss",
            "temperature": 0.0,
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "demo-tool",
                        "description": "Do a thing.",
                        "parameters": {"type": "object"},
                        "strict": True,
                    },
                }
            ],
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        },
        response_body={
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "demo-tool",
                                    "arguments": '{"value":"x"}',
                                },
                            }
                        ],
                    },
                }
            ]
        },
    )


def test_embed_batch_maps_vectors_from_litellm_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embedding batch should map all returned embedding rows into typed vectors."""
    fake_module = _FakeLiteLlmModule(
        embedding_response={
            "data": [
                {"embedding": [0.1, 0.2]},
                {"embedding": [0.3, 0.4]},
            ]
        }
    )
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    adapter = LiteLlmLibraryAdapter(settings=_settings())

    result = adapter.embed_batch(
        provider="ollama",
        model="mxbai-embed-large",
        texts=["a", "b"],
    )

    assert len(result) == 2
    assert result[0].values == (0.1, 0.2)
    assert result[1].values == (0.3, 0.4)
    assert result[0].raw_call == AdapterProviderCallAudit(
        request_api_base="http://localhost:11434",
        request_headers={},
        request_body={
            "model": "ollama/mxbai-embed-large",
            "temperature": 0.0,
            "input": ["a", "b"],
        },
        response_body={
            "data": [
                {"embedding": [0.1, 0.2]},
                {"embedding": [0.3, 0.4]},
            ]
        },
    )
    assert fake_module.embedding_calls[0]["model"] == "ollama/mxbai-embed-large"
    assert callable(fake_module.embedding_calls[0]["logger_fn"])


def test_provider_raw_json_logger_emits_request_and_response_payloads() -> None:
    """Raw JSON logger should emit LiteLLM provider request and response payloads."""
    logger = MagicMock()
    capture = adapter_module._RawCallCapture()
    callback = adapter_module._provider_raw_json_logger(
        logger=logger,
        provider="anthropic",
        model="claude-sonnet-4-6",
        operation="completion",
        capture=capture,
    )

    callback(
        {
            "log_event_type": "pre_api_call",
            "raw_request_typed_dict": {
                "raw_request_api_base": "https://api.anthropic.com/v1/messages",
                "raw_request_headers": {"authorization": "Bearer ****1234"},
                "raw_request_body": {"model": "claude-sonnet-4-6", "messages": []},
            },
        }
    )
    callback(
        {
            "log_event_type": "post_api_call",
            "original_response": {"id": "msg_123", "content": []},
        }
    )

    assert logger.verbose.call_count == 2
    request_message = logger.verbose.call_args_list[0].args[1]
    response_message = logger.verbose.call_args_list[1].args[1]
    assert '"event": "provider_raw_request"' in request_message
    assert '"raw_request_api_base"' not in request_message
    assert '"api_base": "https://api.anthropic.com/v1/messages"' in request_message
    assert '"body": {"model": "claude-sonnet-4-6", "messages": []}' in request_message
    assert '"event": "provider_raw_response"' in response_message
    assert '"response": {"id": "msg_123", "content": []}' in response_message
    assert capture.to_model() == AdapterProviderCallAudit(
        request_api_base="https://api.anthropic.com/v1/messages",
        request_headers={"authorization": "Bearer ****1234"},
        request_body={"model": "claude-sonnet-4-6", "messages": []},
        response_body={"id": "msg_123", "content": []},
    )


def test_chat_uses_provider_api_key_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider api_key_env should resolve from runtime environment for calls."""
    fake_module = _FakeLiteLlmModule()
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    monkeypatch.setenv("OPENAI_API_KEY", "token-123")
    adapter = LiteLlmLibraryAdapter(
        settings=LiteLlmAdapterSettings(
            providers={"openai": LiteLlmProviderSettings(api_key_env="OPENAI_API_KEY")}
        )
    )

    adapter.chat(provider="openai", model="gpt-4o-mini", prompt="hi")

    assert fake_module.completion_calls[0]["api_key"] == "token-123"


def test_chat_raises_internal_error_for_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown provider names should fail as explicit adapter misconfiguration."""
    fake_module = _FakeLiteLlmModule()
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    adapter = LiteLlmLibraryAdapter(settings=_settings())

    with pytest.raises(
        AdapterInternalError, match="provider 'openai' is not configured"
    ):
        adapter.chat(provider="openai", model="gpt-4o-mini", prompt="hi")


def test_chat_raises_dependency_error_for_timeout_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeout-like failures should map to dependency error category."""
    fake_module = _FakeLiteLlmModule(completion_exception=TimeoutError("timed out"))
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    adapter = LiteLlmLibraryAdapter(settings=_settings())

    with pytest.raises(AdapterDependencyError, match="timed out"):
        adapter.chat(provider="ollama", model="gpt-oss", prompt="hi")


def test_chat_retries_timeout_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeout-like failures should retry with the configured backoff policy."""
    fake_module = _FakeLiteLlmModule(
        completion_exceptions=[TimeoutError("timed out"), TimeoutError("timed out")]
    )
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    sleep = MagicMock()
    monkeypatch.setattr(adapter_module, "sleep", sleep)
    monkeypatch.setattr(adapter_module, "random", lambda: 0.5)
    adapter = LiteLlmLibraryAdapter(settings=_settings())

    result = adapter.chat(provider="ollama", model="gpt-oss", prompt="hi")

    assert result.text == "hello"
    assert len(fake_module.completion_calls) == 3
    assert sleep.call_args_list == [call(0.5), call(1.0)]


def test_chat_with_tools_exhausts_timeout_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool chat should raise after exhausting the timeout retry budget."""
    fake_module = _FakeLiteLlmModule(
        completion_exceptions=[
            TimeoutError("timed out"),
            TimeoutError("timed out"),
            TimeoutError("timed out"),
        ]
    )
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    sleep = MagicMock()
    monkeypatch.setattr(adapter_module, "sleep", sleep)
    monkeypatch.setattr(adapter_module, "random", lambda: 0.5)
    adapter = LiteLlmLibraryAdapter(settings=_settings())

    with pytest.raises(AdapterDependencyError, match="timed out"):
        adapter.chat_with_tools(
            provider="ollama",
            model="gpt-oss",
            messages=(AdapterChatMessage(role="user", content="hello"),),
            tools=(
                AdapterChatToolDefinition(
                    name="demo-tool",
                    description="Do a thing.",
                    parameters_json_schema={"type": "object"},
                ),
            ),
        )

    assert len(fake_module.completion_calls) == 3
    assert sleep.call_args_list == [call(0.5), call(1.0)]


def test_chat_with_tools_preserves_request_and_error_payload_on_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rate-limit failures should still produce one non-empty raw call audit."""
    fake_module = _FakeLiteLlmModule(
        completion_exception=litellm.RateLimitError(
            message="too many tokens",
            llm_provider="anthropic",
            model="claude-sonnet-4-6",
            response=httpx.Response(
                status_code=429,
                headers={"retry-after": "60"},
                request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
            ),
        )
    )
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    adapter = LiteLlmLibraryAdapter(settings=_settings())

    with pytest.raises(AdapterDependencyError) as exc_info:
        adapter.chat_with_tools(
            provider="ollama",
            model="gpt-oss",
            messages=(AdapterChatMessage(role="user", content="hello"),),
            tools=(
                AdapterChatToolDefinition(
                    name="demo-tool",
                    description="Do a thing.",
                    parameters_json_schema={"type": "object"},
                ),
            ),
        )

    raw_call = exc_info.value.raw_call
    assert raw_call is not None
    assert raw_call.request_body == {
        "model": "ollama/gpt-oss",
        "temperature": 0.0,
        "messages": [{"role": "user", "content": "hello"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "demo-tool",
                    "description": "Do a thing.",
                    "parameters": {"type": "object"},
                },
            }
        ],
    }
    assert raw_call.response_body == {
        "status_code": 429,
        "reason": "Too Many Requests",
        "headers": {"retry-after": "60"},
    }


def test_embed_raises_internal_error_for_non_dependency_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-network runtime failures should map to adapter internal errors."""
    fake_module = _FakeLiteLlmModule(embedding_exception=RuntimeError("bad transform"))
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    adapter = LiteLlmLibraryAdapter(settings=_settings())

    with pytest.raises(AdapterInternalError, match="bad transform"):
        adapter.embed(provider="ollama", model="embed-a", text="hello")


def test_health_returns_not_ready_when_litellm_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Health should degrade when the litellm dependency cannot be imported."""

    def _raise_missing() -> object:
        raise AdapterInternalError("litellm package is not installed")

    monkeypatch.setattr(adapter_module, "_load_litellm_module", _raise_missing)
    adapter = LiteLlmLibraryAdapter(settings=_settings())

    result = adapter.health()

    assert result.adapter_ready is False
    assert result.detail == "litellm package is not installed"


def test_health_returns_not_ready_when_api_key_env_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Health should report configuration failure for unresolved provider api_key_env."""
    fake_module = _FakeLiteLlmModule()
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    adapter = LiteLlmLibraryAdapter(
        settings=LiteLlmAdapterSettings(
            providers={"openai": LiteLlmProviderSettings(api_key_env="OPENAI_API_KEY")}
        )
    )

    result = adapter.health()

    assert result.adapter_ready is False
    assert "OPENAI_API_KEY" in result.detail
