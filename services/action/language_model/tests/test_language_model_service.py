"""Behavior tests for Language Model Service implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pytest
from packages.brain_shared.config import BrainSettings
from packages.brain_shared.envelope import EnvelopeKind, new_meta
from resources.adapters.litellm import (
    AdapterChatResult,
    AdapterDependencyError,
    AdapterEmbeddingResult,
    AdapterHealthResult,
    AdapterInternalError,
    LiteLlmAdapter,
)
from services.action.language_model.config import (
    LanguageModelProfileSettings,
    LanguageModelServiceSettings,
    resolve_language_model_service_settings,
)
from services.action.language_model.implementation import DefaultLanguageModelService
from services.action.language_model.validation import EmbeddingProfile, ReasoningLevel


@dataclass
class _Call:
    provider: str
    model: str


@dataclass
class _ChatCall(_Call):
    prompt: str


@dataclass
class _ChatBatchCall(_Call):
    prompts: tuple[str, ...]


@dataclass
class _EmbedCall(_Call):
    text: str


@dataclass
class _EmbedBatchCall(_Call):
    texts: tuple[str, ...]


class _FakeAdapter(LiteLlmAdapter):
    """In-memory adapter fake for LMS service behavior tests."""

    def __init__(self) -> None:
        self.chat_calls: list[_ChatCall] = []
        self.chat_batch_calls: list[_ChatBatchCall] = []
        self.embed_calls: list[_EmbedCall] = []
        self.embed_batch_calls: list[_EmbedBatchCall] = []
        self.raise_chat: Exception | None = None
        self.raise_chat_batch: Exception | None = None
        self.raise_embed: Exception | None = None
        self.raise_embed_batch: Exception | None = None
        self.health_result = AdapterHealthResult(adapter_ready=True, detail="ok")

    def chat(
        self,
        *,
        provider: str,
        model: str,
        prompt: str,
    ) -> AdapterChatResult:
        self.chat_calls.append(_ChatCall(provider=provider, model=model, prompt=prompt))
        if self.raise_chat is not None:
            raise self.raise_chat
        return AdapterChatResult(text=f"ok:{prompt}", provider=provider, model=model)

    def chat_batch(
        self,
        *,
        provider: str,
        model: str,
        prompts: Sequence[str],
    ) -> list[AdapterChatResult]:
        self.chat_batch_calls.append(
            _ChatBatchCall(provider=provider, model=model, prompts=tuple(prompts))
        )
        if self.raise_chat_batch is not None:
            raise self.raise_chat_batch
        return [
            AdapterChatResult(text=f"ok:{item}", provider=provider, model=model)
            for item in prompts
        ]

    def embed(
        self,
        *,
        provider: str,
        model: str,
        text: str,
    ) -> AdapterEmbeddingResult:
        self.embed_calls.append(_EmbedCall(provider=provider, model=model, text=text))
        if self.raise_embed is not None:
            raise self.raise_embed
        return AdapterEmbeddingResult(
            values=(0.1, 0.2),
            provider=provider,
            model=model,
        )

    def embed_batch(
        self,
        *,
        provider: str,
        model: str,
        texts: Sequence[str],
    ) -> list[AdapterEmbeddingResult]:
        self.embed_batch_calls.append(
            _EmbedBatchCall(provider=provider, model=model, texts=tuple(texts))
        )
        if self.raise_embed_batch is not None:
            raise self.raise_embed_batch
        return [
            AdapterEmbeddingResult(
                values=(0.1 + index, 0.2 + index),
                provider=provider,
                model=model,
            )
            for index, _ in enumerate(texts)
        ]

    def health(self) -> AdapterHealthResult:
        return self.health_result


def _settings() -> LanguageModelServiceSettings:
    """Build deterministic service settings for tests."""
    return LanguageModelServiceSettings(
        embedding=LanguageModelProfileSettings(provider="ollama", model="embed-a"),
        quick=LanguageModelProfileSettings(provider="openai", model="chat-q"),
        standard=LanguageModelProfileSettings(provider="ollama", model="chat-a"),
        deep=LanguageModelProfileSettings(provider="openai", model="chat-d"),
    )


def _meta() -> object:
    """Build valid envelope metadata for tests."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_chat_uses_default_profile_by_default() -> None:
    """Single chat should use standard reasoning level by default."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.chat(meta=_meta(), prompt="hello")

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.text == "ok:hello"
    assert result.payload.value.model == "chat-a"
    assert adapter.chat_calls == [
        _ChatCall(provider="ollama", model="chat-a", prompt="hello")
    ]


def test_chat_deep_uses_deep_profile_when_set() -> None:
    """Deep chat should use configured deep profile."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.chat(
        meta=_meta(),
        prompt="hello",
        profile=ReasoningLevel.DEEP,
    )

    assert result.ok is True
    assert adapter.chat_calls == [
        _ChatCall(provider="openai", model="chat-d", prompt="hello")
    ]


def test_chat_quick_uses_quick_profile_when_set() -> None:
    """Quick chat should use configured quick profile."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.chat(meta=_meta(), prompt="hello", profile=ReasoningLevel.QUICK)

    assert result.ok is True
    assert adapter.chat_calls == [
        _ChatCall(provider="openai", model="chat-q", prompt="hello")
    ]


def test_chat_batch_trims_prompts_and_maps_payload() -> None:
    """Chat batch should normalize prompts and map adapter results in order."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.chat_batch(meta=_meta(), prompts=["  one  ", "two "])

    assert result.ok is True
    assert result.payload is not None
    assert [item.text for item in result.payload.value] == ["ok:one", "ok:two"]
    assert adapter.chat_batch_calls == [
        _ChatBatchCall(provider="ollama", model="chat-a", prompts=("one", "two"))
    ]


def test_embed_uses_embedding_profile_by_default() -> None:
    """Single embed should use embedding profile and map vector payload."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.embed(meta=_meta(), text=" hello ")

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.values == (0.1, 0.2)
    assert adapter.embed_calls == [
        _EmbedCall(provider="ollama", model="embed-a", text="hello")
    ]


def test_embed_batch_trims_texts_and_maps_payload() -> None:
    """Embed batch should normalize all texts and preserve result ordering."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.embed_batch(meta=_meta(), texts=[" a ", "b"])

    assert result.ok is True
    assert result.payload is not None
    assert [item.values for item in result.payload.value] == [(0.1, 0.2), (1.1, 1.2)]
    assert adapter.embed_batch_calls == [
        _EmbedBatchCall(provider="ollama", model="embed-a", texts=("a", "b"))
    ]


def test_embed_rejects_non_embedding_profile() -> None:
    """Embed operation should enforce embedding profile selector."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.embed(
        meta=_meta(),
        text="hello",
        profile=ReasoningLevel.STANDARD,  # type: ignore[arg-type]
    )

    assert result.ok is False
    assert len(result.errors) == 1
    assert result.errors[0].message == "profile: Input should be 'embedding'"
    assert adapter.embed_calls == []


def test_chat_rejects_embedding_profile() -> None:
    """Chat operation should reject embedding profile selector."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.chat(
        meta=_meta(),
        prompt="hello",
        profile=EmbeddingProfile.EMBEDDING,  # type: ignore[arg-type]
    )

    assert result.ok is False
    assert len(result.errors) == 1
    assert (
        result.errors[0].message
        == "profile: Input should be 'quick', 'standard' or 'deep'"
    )
    assert adapter.chat_calls == []


def test_resolve_settings_quick_falls_back_to_standard_when_unset() -> None:
    """Config resolver should map empty quick profile fields to standard."""
    settings = BrainSettings(
        components={
            "service": {
                "language_model": {
                    "embedding": {"provider": "ollama", "model": "embed-a"},
                    "standard": {"provider": "ollama", "model": "chat-a"},
                    "quick": {"provider": "", "model": ""},
                }
            }
        }
    )

    resolved = resolve_language_model_service_settings(settings)

    assert resolved.quick.provider == "ollama"
    assert resolved.quick.model == "chat-a"


def test_resolve_settings_deep_falls_back_to_standard_when_unset() -> None:
    """Config resolver should map empty deep profile fields to standard."""
    settings = BrainSettings(
        components={
            "service": {
                "language_model": {
                    "embedding": {"provider": "ollama", "model": "embed-a"},
                    "standard": {"provider": "ollama", "model": "chat-a"},
                    "deep": {"provider": "", "model": ""},
                }
            }
        }
    )

    resolved = resolve_language_model_service_settings(settings)

    assert resolved.deep.provider == "ollama"
    assert resolved.deep.model == "chat-a"


def test_resolve_settings_requires_standard_profile() -> None:
    """Config resolver should fail when standard profile is missing."""
    settings = BrainSettings(
        components={
            "service": {
                "language_model": {
                    "embedding": {"provider": "ollama", "model": "embed-a"},
                }
            }
        }
    )

    with pytest.raises(Exception) as exc_info:
        resolve_language_model_service_settings(settings)
    assert "standard" in str(exc_info.value)


def test_chat_batch_rejects_empty_prompts() -> None:
    """Chat batch should reject empty prompt sequences before adapter calls."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.chat_batch(meta=_meta(), prompts=[])

    assert result.ok is False
    assert len(result.errors) == 1
    assert result.errors[0].message == "prompts: Value error, prompts must not be empty"
    assert adapter.chat_batch_calls == []


def test_embed_batch_rejects_empty_item() -> None:
    """Embed batch should identify the failing item index in validation errors."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.embed_batch(meta=_meta(), texts=["good", " "])

    assert result.ok is False
    assert len(result.errors) == 1
    assert result.errors[0].message == "texts: Value error, texts[1] is required"
    assert adapter.embed_batch_calls == []


def test_chat_rejects_invalid_meta_before_adapter_call() -> None:
    """Chat should fail fast for invalid metadata without touching the adapter."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)
    invalid_meta = _meta().model_copy(update={"source": ""})

    result = service.chat(meta=invalid_meta, prompt="hello")

    assert result.ok is False
    assert len(result.errors) == 1
    assert result.errors[0].message == "metadata.source is required"
    assert adapter.chat_calls == []


def test_chat_maps_dependency_failures_to_error_envelope() -> None:
    """Adapter dependency failures should return dependency-category errors."""
    adapter = _FakeAdapter()
    adapter.raise_chat = AdapterDependencyError("adapter down")
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.chat(meta=_meta(), prompt="hello")

    assert result.ok is False
    assert len(result.errors) == 1
    assert result.errors[0].category.value == "dependency"
    assert result.errors[0].metadata == {"adapter": "adapter_litellm"}


def test_embed_batch_maps_internal_failures_to_error_envelope() -> None:
    """Adapter internal failures should become internal-category envelope errors."""
    adapter = _FakeAdapter()
    adapter.raise_embed_batch = AdapterInternalError("bad adapter payload")
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.embed_batch(meta=_meta(), texts=["hello"])

    assert result.ok is False
    assert len(result.errors) == 1
    assert result.errors[0].category.value == "internal"
    assert result.errors[0].message == "bad adapter payload"
    assert result.errors[0].metadata == {"adapter": "adapter_litellm"}


def test_health_maps_adapter_readiness_into_service_payload() -> None:
    """Service health should always report service readiness and adapter detail."""
    adapter = _FakeAdapter()
    adapter.health_result = AdapterHealthResult(
        adapter_ready=False,
        detail="litellm unavailable",
    )
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.health(meta=_meta())

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.service_ready is True
    assert result.payload.value.adapter_ready is False
    assert result.payload.value.detail == "litellm unavailable"
