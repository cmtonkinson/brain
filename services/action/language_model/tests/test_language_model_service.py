"""Behavior tests for Language Model Service implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from packages.brain_shared.config import (
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)
from packages.brain_shared.envelope import EnvelopeKind, new_meta
from packages.brain_shared.language_model import (
    InferenceRequest,
    InferenceToolCall,
    InferenceToolCallBatchEvent,
    InferenceToolDefinition,
    InferenceToolResult,
    InferenceToolResultBatchEvent,
    InferenceToolResultPayload,
)
from resources.adapters.litellm import (
    AdapterChatResult,
    AdapterChatToolCall,
    AdapterDependencyError,
    AdapterEmbeddingResult,
    AdapterHealthResult,
    AdapterInternalError,
    AdapterProviderCallAudit,
    AdapterToolChatResult,
    LiteLlmAdapter,
)
from services.action.language_model.config import (
    LanguageModelProfileSettings,
    LanguageModelServiceSettings,
    resolve_language_model_service_settings,
)
from services.action.language_model.data.repository import (
    InMemoryLanguageModelCallAuditRepository,
)
from services.action.language_model.implementation import DefaultLanguageModelService
from services.action.language_model.validation import EmbeddingProfile, ReasoningLevel
from tests.helpers.inference_request import make_inference_request


@dataclass
class _Call:
    provider: str
    model: str


@dataclass
class _ChatCall(_Call):
    system_prompt: str
    prompt: str


@dataclass
class _ChatBatchCall(_Call):
    prompts: tuple[str, ...]


@dataclass
class _ChatWithToolsCall(_Call):
    inference_request: InferenceRequest


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
        self.chat_with_tools_calls: list[_ChatWithToolsCall] = []
        self.embed_calls: list[_EmbedCall] = []
        self.embed_batch_calls: list[_EmbedBatchCall] = []
        self.raise_chat: Exception | None = None
        self.raise_chat_batch: Exception | None = None
        self.raise_chat_with_tools: Exception | None = None
        self.raise_embed: Exception | None = None
        self.raise_embed_batch: Exception | None = None
        self.health_result = AdapterHealthResult(adapter_ready=True, detail="ok")

    def chat(
        self,
        *,
        provider: str,
        model: str,
        system_prompt: str = "",
        prompt: str,
    ) -> AdapterChatResult:
        self.chat_calls.append(
            _ChatCall(
                provider=provider,
                model=model,
                system_prompt=system_prompt,
                prompt=prompt,
            )
        )
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

    def chat_with_tools(
        self,
        *,
        provider: str,
        model: str,
        inference_request: InferenceRequest,
    ) -> AdapterToolChatResult:
        self.chat_with_tools_calls.append(
            _ChatWithToolsCall(
                provider=provider,
                model=model,
                inference_request=inference_request,
            )
        )
        if self.raise_chat_with_tools is not None:
            raise self.raise_chat_with_tools
        return AdapterToolChatResult(
            text=None,
            tool_calls=(
                AdapterChatToolCall(
                    tool_name="demo-tool",
                    args_json='{"value":"x"}',
                    tool_call_id="call-1",
                ),
            ),
            provider=provider,
            model=model,
            finish_reason="tool_call",
        )

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
        document_embedding=LanguageModelProfileSettings(
            provider="ollama", model="embed-a"
        ),
        capability_embedding=LanguageModelProfileSettings(
            provider="ollama", model="embed-cap"
        ),
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
        _ChatCall(
            provider="ollama",
            model="chat-a",
            system_prompt="",
            prompt="hello",
        )
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
        _ChatCall(
            provider="openai",
            model="chat-d",
            system_prompt="",
            prompt="hello",
        )
    ]


def test_chat_quick_uses_quick_profile_when_set() -> None:
    """Quick chat should use configured quick profile."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.chat(meta=_meta(), prompt="hello", profile=ReasoningLevel.QUICK)

    assert result.ok is True
    assert adapter.chat_calls == [
        _ChatCall(
            provider="openai",
            model="chat-q",
            system_prompt="",
            prompt="hello",
        )
    ]


def test_chat_passes_system_prompt_separately() -> None:
    """Single chat should preserve optional system prompt role separation."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.chat(
        meta=_meta(),
        system_prompt="compress carefully",
        prompt="hello",
    )

    assert result.ok is True
    assert adapter.chat_calls == [
        _ChatCall(
            provider="ollama",
            model="chat-a",
            system_prompt="compress carefully",
            prompt="hello",
        )
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


def test_chat_with_tools_maps_messages_tools_and_response() -> None:
    """Tool-capable chat should route normalized messages and tool calls."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)
    inference_request = make_inference_request(
        system_blocks=(),
        tools=(
            InferenceToolDefinition(
                name="demo-tool",
                description="Do a thing.",
                input_schema={"type": "object"},
            ),
        ),
    )

    result = service.chat_with_tools(meta=_meta(), inference_request=inference_request)

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.finish_reason == "tool_call"
    assert result.payload.value.tool_calls[0].tool_name == "demo-tool"
    assert adapter.chat_with_tools_calls == [
        _ChatWithToolsCall(
            provider="ollama",
            model="chat-a",
            inference_request=inference_request,
        )
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
    assert (
        result.errors[0].message
        == "profile: Input should be 'document_embedding' or 'capability_embedding'"
    )
    assert adapter.embed_calls == []


def test_chat_rejects_embedding_profile() -> None:
    """Chat operation should reject embedding profile selector."""
    adapter = _FakeAdapter()
    service = DefaultLanguageModelService(settings=_settings(), adapter=adapter)

    result = service.chat(
        meta=_meta(),
        prompt="hello",
        profile=EmbeddingProfile.DOCUMENT_EMBEDDING,  # type: ignore[arg-type]
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
    settings = CoreRuntimeSettings(
        core=CoreSettings.model_validate(
            {
                "service": {
                    "language_model": {
                        "document_embedding": {
                            "provider": "ollama",
                            "model": "embed-a",
                        },
                        "capability_embedding": {
                            "provider": "ollama",
                            "model": "embed-cap",
                        },
                        "standard": {"provider": "ollama", "model": "chat-a"},
                        "quick": {"provider": "", "model": ""},
                    }
                }
            }
        ),
        resources=ResourcesSettings.model_validate({}),
    )

    resolved = resolve_language_model_service_settings(settings)

    assert resolved.quick.provider == "ollama"
    assert resolved.quick.model == "chat-a"


def test_resolve_settings_deep_falls_back_to_standard_when_unset() -> None:
    """Config resolver should map empty deep profile fields to standard."""
    settings = CoreRuntimeSettings(
        core=CoreSettings.model_validate(
            {
                "service": {
                    "language_model": {
                        "document_embedding": {
                            "provider": "ollama",
                            "model": "embed-a",
                        },
                        "capability_embedding": {
                            "provider": "ollama",
                            "model": "embed-cap",
                        },
                        "standard": {"provider": "ollama", "model": "chat-a"},
                        "deep": {"provider": "", "model": ""},
                    }
                }
            }
        ),
        resources=ResourcesSettings.model_validate({}),
    )

    resolved = resolve_language_model_service_settings(settings)

    assert resolved.deep.provider == "ollama"
    assert resolved.deep.model == "chat-a"


def test_resolve_settings_defaults_standard_profile_when_missing() -> None:
    """Config resolver should default standard profile when it is omitted."""
    settings = CoreRuntimeSettings(
        core=CoreSettings.model_validate(
            {
                "service": {
                    "language_model": {
                        "document_embedding": {
                            "provider": "ollama",
                            "model": "embed-a",
                        },
                        "capability_embedding": {
                            "provider": "ollama",
                            "model": "embed-cap",
                        },
                    }
                }
            }
        ),
        resources=ResourcesSettings.model_validate({}),
    )

    resolved = resolve_language_model_service_settings(settings)

    assert resolved.standard.provider == "ollama"
    assert resolved.standard.model == "gpt-oss:20b"


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


def test_chat_appends_provider_call_audit_with_raw_payloads() -> None:
    """Successful chat calls should append one raw provider audit row."""
    adapter = _FakeAdapter()
    audit_repository = InMemoryLanguageModelCallAuditRepository()
    raw_call = AdapterProviderCallAudit(
        request_api_base="https://api.example.test/v1/chat",
        request_headers={"authorization": "Bearer ****1234"},
        request_body={
            "model": "chat-a",
            "messages": [{"role": "user", "content": "hello"}],
        },
        response_body={"id": "resp_123", "choices": []},
    )
    adapter.chat = lambda **kwargs: AdapterChatResult(  # type: ignore[method-assign]
        text="ok:hello",
        provider=kwargs["provider"],
        model=kwargs["model"],
        raw_call=raw_call,
    )
    service = DefaultLanguageModelService(
        settings=_settings(),
        adapter=adapter,
        audit_repository=audit_repository,
    )

    result = service.chat(meta=_meta(), prompt="hello")

    assert result.ok is True
    rows = audit_repository.list_rows()
    assert len(rows) == 1
    assert rows[0].operation == "chat"
    assert rows[0].request_phase == "initial"
    assert rows[0].outcome_kind == "final"
    assert rows[0].call_index == 1
    assert rows[0].request_json == {
        "api_base": "https://api.example.test/v1/chat",
        "headers": {"authorization": "Bearer ****1234"},
        "body": {"model": "chat-a", "messages": [{"role": "user", "content": "hello"}]},
    }
    assert rows[0].response_json == {"body": {"id": "resp_123", "choices": []}}


def test_chat_with_tools_marks_followup_and_sequences_audit_rows() -> None:
    """Tool follow-up calls should be classified separately and sequenced by trace."""
    adapter = _FakeAdapter()
    audit_repository = InMemoryLanguageModelCallAuditRepository()
    first_raw_call = AdapterProviderCallAudit(
        request_api_base="https://api.example.test/v1/chat",
        request_headers={},
        request_body={"messages": [{"role": "user", "content": "find resume"}]},
        response_body={"id": "resp_1", "choices": []},
    )
    second_raw_call = AdapterProviderCallAudit(
        request_api_base="https://api.example.test/v1/chat",
        request_headers={},
        request_body={"messages": [{"role": "tool", "content": "search results"}]},
        response_body={"id": "resp_2", "choices": []},
    )
    raw_calls = [first_raw_call, second_raw_call]

    def _chat_with_tools(**kwargs: object) -> AdapterToolChatResult:
        raw_call = raw_calls.pop(0)
        inference_request = kwargs["inference_request"]
        has_tool_message = any(
            item.kind == "tool_result_batch"
            for item in inference_request.live_events  # type: ignore[attr-defined]
        )
        return AdapterToolChatResult(
            text="done" if has_tool_message else None,
            tool_calls=()
            if has_tool_message
            else (
                AdapterChatToolCall(
                    tool_name="demo-tool",
                    args_json='{"value":"x"}',
                    tool_call_id="call-1",
                ),
            ),
            provider=str(kwargs["provider"]),
            model=str(kwargs["model"]),
            finish_reason="stop" if has_tool_message else "tool_call",
            raw_call=raw_call,
        )

    adapter.chat_with_tools = _chat_with_tools  # type: ignore[method-assign]
    service = DefaultLanguageModelService(
        settings=_settings(),
        adapter=adapter,
        audit_repository=audit_repository,
    )
    meta = _meta()

    first = service.chat_with_tools(
        meta=meta,
        inference_request=make_inference_request(),
    )
    second = service.chat_with_tools(
        meta=meta,
        inference_request=make_inference_request(
            live_events=(
                InferenceToolCallBatchEvent(
                    calls=(
                        InferenceToolCall(
                            call_id="call-1",
                            tool_name="demo-tool",
                            arguments={"value": "x"},
                        ),
                    )
                ),
                InferenceToolResultBatchEvent(
                    results=(
                        InferenceToolResult(
                            call_id="call-1",
                            tool_name="demo-tool",
                            result=InferenceToolResultPayload(
                                mime_type="text/plain",
                                text="search results",
                            ),
                        ),
                    )
                ),
            ),
        ),
    )

    assert first.ok is True
    assert second.ok is True
    rows = audit_repository.list_rows()
    assert len(rows) == 2
    assert [row.call_index for row in rows] == [1, 2]
    assert [row.request_phase for row in rows] == ["initial", "tool_followup"]
    assert [row.outcome_kind for row in rows] == ["tool_call", "final"]


def test_chat_error_appends_audit_row_with_error_outcome() -> None:
    """Adapter failures should still append one audit row with raw request data."""
    adapter = _FakeAdapter()
    audit_repository = InMemoryLanguageModelCallAuditRepository()
    adapter.raise_chat = AdapterDependencyError(
        "adapter down",
        raw_call=AdapterProviderCallAudit(
            request_api_base="https://api.example.test/v1/chat",
            request_headers={},
            request_body={"messages": [{"role": "user", "content": "hello"}]},
        ),
    )
    service = DefaultLanguageModelService(
        settings=_settings(),
        adapter=adapter,
        audit_repository=audit_repository,
    )

    result = service.chat(meta=_meta(), prompt="hello")

    assert result.ok is False
    rows = audit_repository.list_rows()
    assert len(rows) == 1
    assert rows[0].outcome_kind == "error"
    assert rows[0].error_message == "adapter down"
    assert rows[0].response_json == {"body": None}
