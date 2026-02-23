"""Unit tests for the in-process LiteLLM adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

import resources.adapters.litellm.litellm_adapter as adapter_module
from resources.adapters.litellm.adapter import (
    AdapterDependencyError,
    AdapterInternalError,
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
    embedding_exception: Exception | None = None
    completion_calls: list[dict[str, Any]] = field(default_factory=list)
    embedding_calls: list[dict[str, Any]] = field(default_factory=list)

    def completion(self, **kwargs: Any) -> object:
        self.completion_calls.append(kwargs)
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
    assert fake_module.embedding_calls[0]["model"] == "ollama/mxbai-embed-large"


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
