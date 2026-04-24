"""Behavior tests for Language Service implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from lib.shared.config import (
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)
from lib.shared.envelope import EnvelopeKind, new_meta
from lib.shared.language_model import (
    InferenceAssistantTextEvent,
    InferenceRequest,
    InferenceSystemBlock,
    InferenceToolCall,
    InferenceToolCallBatchEvent,
    InferenceToolDefinition,
    InferenceToolResult,
    InferenceToolResultBatchEvent,
    InferenceToolResultPayload,
)
from resources.adapters.llm import (
    AdapterChatResult,
    AdapterChatToolCall,
    AdapterDependencyError,
    AdapterEmbeddingResult,
    AdapterHealthResult,
    AdapterInternalError,
    AdapterProviderCallAudit,
    AdapterToolChatResult,
    LlmAdapter,
)
from services.effect.language.config import (
    LanguageEmbeddingProfileSettings,
    LanguageProfileSettings,
    LanguageServiceSettings,
    resolve_language_service_settings,
)
from services.effect.language.data.repository import (
    InMemoryLanguageModelCallAuditRepository,
    InMemoryLanguageModelTurnCacheHopRepository,
)
from services.effect.language.implementation import DefaultLanguageService
from services.effect.language.validation import EmbeddingProfile, ReasoningLevel
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
    dimensions: int | None = None


@dataclass
class _EmbedBatchCall(_Call):
    texts: tuple[str, ...]
    dimensions: int | None = None


class _FakeAdapter(LlmAdapter):
    """In-memory adapter fake for Language service behavior tests."""

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
        dimensions: int | None = None,
    ) -> AdapterEmbeddingResult:
        self.embed_calls.append(
            _EmbedCall(
                provider=provider,
                model=model,
                text=text,
                dimensions=dimensions,
            )
        )
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
        dimensions: int | None = None,
    ) -> list[AdapterEmbeddingResult]:
        self.embed_batch_calls.append(
            _EmbedBatchCall(
                provider=provider,
                model=model,
                texts=tuple(texts),
                dimensions=dimensions,
            )
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


def _settings() -> LanguageServiceSettings:
    """Build deterministic service settings for tests."""
    return LanguageServiceSettings(
        document_embedding=LanguageEmbeddingProfileSettings(
            provider="ollama", model="embed-a", dimensions=1024
        ),
        op_embedding=LanguageEmbeddingProfileSettings(
            provider="ollama", model="embed-cap", dimensions=1024
        ),
        quick=LanguageProfileSettings(provider="openai", model="chat-q"),
        standard=LanguageProfileSettings(provider="ollama", model="chat-a"),
        deep=LanguageProfileSettings(provider="openai", model="chat-d"),
    )


def _meta() -> object:
    """Build valid envelope metadata for tests."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_chat_uses_default_profile_by_default() -> None:
    """Single chat should use standard reasoning level by default."""
    adapter = _FakeAdapter()
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)

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
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)

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
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)

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
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)

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
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)

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
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)
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
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)

    result = service.embed(meta=_meta(), text=" hello ")

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.values == (0.1, 0.2)
    assert adapter.embed_calls == [
        _EmbedCall(
            provider="ollama",
            model="embed-a",
            text="hello",
            dimensions=1024,
        )
    ]


def test_embed_batch_trims_texts_and_maps_payload() -> None:
    """Embed batch should normalize all texts and preserve result ordering."""
    adapter = _FakeAdapter()
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)

    result = service.embed_batch(meta=_meta(), texts=[" a ", "b"])

    assert result.ok is True
    assert result.payload is not None
    assert [item.values for item in result.payload.value] == [(0.1, 0.2), (1.1, 1.2)]
    assert adapter.embed_batch_calls == [
        _EmbedBatchCall(
            provider="ollama",
            model="embed-a",
            texts=("a", "b"),
            dimensions=1024,
        )
    ]


def test_embed_rejects_non_embedding_profile() -> None:
    """Embed operation should enforce embedding profile selector."""
    adapter = _FakeAdapter()
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)

    result = service.embed(
        meta=_meta(),
        text="hello",
        profile=ReasoningLevel.STANDARD,  # type: ignore[arg-type]
    )

    assert result.ok is False
    assert len(result.errors) == 1
    assert (
        result.errors[0].message
        == "profile: Input should be 'document_embedding' or 'op_embedding'"
    )
    assert adapter.embed_calls == []


def test_chat_rejects_embedding_profile() -> None:
    """Chat operation should reject embedding profile selector."""
    adapter = _FakeAdapter()
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)

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
        core=CoreSettings.model_validate({}),
        resources=ResourcesSettings.model_validate({}),
        component_settings={
            "language": {
                "document_embedding": {
                    "provider": "ollama",
                    "model": "embed-a",
                    "dimensions": 1024,
                },
                "op_embedding": {
                    "provider": "ollama",
                    "model": "embed-cap",
                    "dimensions": 1024,
                },
                "standard": {"provider": "ollama", "model": "chat-a"},
                "quick": {"provider": "", "model": ""},
            }
        },
    )

    resolved = resolve_language_service_settings(settings)

    assert resolved.quick.provider == "ollama"
    assert resolved.quick.model == "chat-a"


def test_resolve_settings_deep_falls_back_to_standard_when_unset() -> None:
    """Config resolver should map empty deep profile fields to standard."""
    settings = CoreRuntimeSettings(
        core=CoreSettings.model_validate({}),
        resources=ResourcesSettings.model_validate({}),
        component_settings={
            "language": {
                "document_embedding": {
                    "provider": "ollama",
                    "model": "embed-a",
                    "dimensions": 1024,
                },
                "op_embedding": {
                    "provider": "ollama",
                    "model": "embed-cap",
                    "dimensions": 1024,
                },
                "standard": {"provider": "ollama", "model": "chat-a"},
                "deep": {"provider": "", "model": ""},
            }
        },
    )

    resolved = resolve_language_service_settings(settings)

    assert resolved.deep.provider == "ollama"
    assert resolved.deep.model == "chat-a"


def test_resolve_settings_defaults_standard_profile_when_missing() -> None:
    """Config resolver should default chat profiles when they are omitted."""
    settings = CoreRuntimeSettings(
        core=CoreSettings.model_validate({}),
        resources=ResourcesSettings.model_validate({}),
        component_settings={
            "language": {
                "document_embedding": {
                    "provider": "ollama",
                    "model": "embed-a",
                    "dimensions": 1024,
                },
                "op_embedding": {
                    "provider": "ollama",
                    "model": "embed-cap",
                    "dimensions": 1024,
                },
            }
        },
    )

    resolved = resolve_language_service_settings(settings)

    assert resolved.document_embedding.provider == "ollama"
    assert resolved.document_embedding.model == "embed-a"
    assert resolved.document_embedding.dimensions == 1024
    assert resolved.op_embedding.provider == "ollama"
    assert resolved.op_embedding.model == "embed-cap"
    assert resolved.op_embedding.dimensions == 1024
    assert resolved.quick.provider == "anthropic"
    assert resolved.quick.model == "claude-haiku-4-5-20251001"
    assert resolved.standard.provider == "anthropic"
    assert resolved.standard.model == "claude-sonnet-4-6-20251001"
    assert resolved.deep.provider == "anthropic"
    assert resolved.deep.model == "claude-opus-4-7"


def test_chat_batch_rejects_empty_prompts() -> None:
    """Chat batch should reject empty prompt sequences before adapter calls."""
    adapter = _FakeAdapter()
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)

    result = service.chat_batch(meta=_meta(), prompts=[])

    assert result.ok is False
    assert len(result.errors) == 1
    assert result.errors[0].message == "prompts: Value error, prompts must not be empty"
    assert adapter.chat_batch_calls == []


def test_embed_batch_rejects_empty_item() -> None:
    """Embed batch should identify the failing item index in validation errors."""
    adapter = _FakeAdapter()
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)

    result = service.embed_batch(meta=_meta(), texts=["good", " "])

    assert result.ok is False
    assert len(result.errors) == 1
    assert result.errors[0].message == "texts: Value error, texts[1] is required"
    assert adapter.embed_batch_calls == []


def test_chat_rejects_invalid_meta_before_adapter_call() -> None:
    """Chat should fail fast for invalid metadata without touching the adapter."""
    adapter = _FakeAdapter()
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)
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
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)

    result = service.chat(meta=_meta(), prompt="hello")

    assert result.ok is False
    assert len(result.errors) == 1
    assert result.errors[0].category.value == "dependency"
    assert result.errors[0].metadata == {"adapter": "adapter_llm"}


def test_embed_batch_maps_internal_failures_to_error_envelope() -> None:
    """Adapter internal failures should become internal-category envelope errors."""
    adapter = _FakeAdapter()
    adapter.raise_embed_batch = AdapterInternalError("bad adapter payload")
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)

    result = service.embed_batch(meta=_meta(), texts=["hello"])

    assert result.ok is False
    assert len(result.errors) == 1
    assert result.errors[0].category.value == "internal"
    assert result.errors[0].message == "bad adapter payload"
    assert result.errors[0].metadata == {"adapter": "adapter_llm"}


def test_health_maps_adapter_readiness_into_service_payload() -> None:
    """Service health should always report service readiness and adapter detail."""
    adapter = _FakeAdapter()
    adapter.health_result = AdapterHealthResult(
        adapter_ready=False,
        detail="llm unavailable",
    )
    service = DefaultLanguageService(settings=_settings(), adapter=adapter)

    result = service.health(meta=_meta())

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.service_ready is True
    assert result.payload.value.adapter_ready is False
    assert result.payload.value.detail == "llm unavailable"


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
    service = DefaultLanguageService(
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
    service = DefaultLanguageService(
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


def test_chat_with_tools_appends_turn_cache_hop_telemetry() -> None:
    """Tool-capable chat calls should persist one per-hop cache telemetry row."""
    adapter = _FakeAdapter()
    audit_repository = InMemoryLanguageModelCallAuditRepository()
    turn_cache_hop_repository = InMemoryLanguageModelTurnCacheHopRepository()
    raw_call = AdapterProviderCallAudit(
        request_api_base="https://api.example.test/v1/messages",
        request_headers={},
        request_body={
            "model": "chat-a",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "prefix",
                            "cache_control": {"type": "ephemeral"},
                        },
                        {"type": "text", "text": "question"},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "content": "result"},
                        {
                            "type": "text",
                            "text": " ",
                            "cache_control": {"type": "ephemeral"},
                        },
                    ],
                },
            ],
        },
        response_body={
            "id": "resp_123",
            "usage": {
                "cache_creation_input_tokens": 200,
                "cache_read_input_tokens": 100,
            },
        },
    )
    adapter.chat_with_tools = lambda **kwargs: AdapterToolChatResult(  # type: ignore[method-assign]
        text=None,
        tool_calls=(
            AdapterChatToolCall(
                tool_name="demo-tool",
                args_json='{"value":"x"}',
                tool_call_id="call-1",
            ),
        ),
        provider=str(kwargs["provider"]),
        model=str(kwargs["model"]),
        finish_reason="tool_call",
        raw_call=raw_call,
    )
    service = DefaultLanguageService(
        settings=_settings(),
        adapter=adapter,
        audit_repository=audit_repository,
        turn_cache_hop_repository=turn_cache_hop_repository,
    )

    result = service.chat_with_tools(
        meta=_meta(),
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
                                text="result",
                            ),
                        ),
                    ),
                    cache_after=True,
                ),
            ),
        ),
    )

    assert result.ok is True
    rows = turn_cache_hop_repository.list_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row.hop_ordinal == 1
    assert row.call_index == 1
    assert row.placed_cachepoint_ordinal == 1
    assert row.cp0_active is True
    assert row.cp1_active is True
    assert row.cp2_active is False
    assert row.active_cachepoint_count == 2
    assert row.cache_creation_input_tokens == 200
    assert row.cache_read_input_tokens == 100
    assert row.estimated_write_premium_token_equiv == 50.0
    assert row.estimated_read_savings_token_equiv == 90.0
    assert row.estimated_net_token_equiv == 40.0


def test_language_generation_observation_maps_langfuse_usage_and_content(
    monkeypatch,
) -> None:
    """Provider audit payloads should map to Langfuse generation attributes."""
    from services.effect.language import implementation as module

    class _Span:
        """In-memory span for observation attribute assertions."""

        def __init__(self) -> None:
            self.attributes: dict[str, object] = {}

        def set_attribute(self, key: str, value: object) -> None:
            self.attributes[key] = value

    monkeypatch.setattr(module, "is_llm_content_capture_enabled", lambda: True)
    span = _Span()
    module._complete_language_generation_observation(
        span=span,
        outcome="success",
        provider="anthropic",
        model="claude-test",
        finish_reason="stop",
        raw_call=AdapterProviderCallAudit(
            request_body={"model": "claude-test", "messages": []},
            response_body={
                "model": "claude-test",
                "usage": {
                    "input_tokens": 11,
                    "output_tokens": 7,
                    "cache_creation_input_tokens": 3,
                    "cache_read_input_tokens": 5,
                },
            },
        ),
        observation_input={"message": "hello", "request_phase": "initial"},
    )

    assert span.attributes["langfuse.observation.model.name"] == "claude-test"
    assert span.attributes["gen_ai.system"] == "anthropic"
    assert span.attributes["gen_ai.usage.input_tokens"] == 11
    assert span.attributes["gen_ai.usage.output_tokens"] == 7
    assert '"input": 11' in span.attributes["langfuse.observation.usage_details"]
    assert '"message": "hello"' in span.attributes["langfuse.observation.input"]
    assert "claude-test" in span.attributes["langfuse.observation.output"]


def test_langfuse_tool_observation_input_exposes_canonical_ir() -> None:
    """Tool-call Langfuse input should expose the canonical inference request."""
    from services.effect.language import implementation as module

    inference_request = make_inference_request(
        system_blocks=(
            InferenceSystemBlock(
                kind="assistant_persona",
                text="You are Brain.",
                cache_after=True,
            ),
            InferenceSystemBlock(
                kind="operator_profile",
                text="Refer to me as boss.",
            ),
        ),
        live_events=(InferenceAssistantTextEvent(text="model draft"),),
    )

    payload = module._langfuse_observation_input(
        inference_request,
        request_phase="initial",
    )

    assert payload["request_phase"] == "initial"
    assert payload["inference_request"] == inference_request.model_dump(mode="python")
    assert payload["inference_request"]["system"]["blocks"][0] == {
        "kind": "assistant_persona",
        "text": "You are Brain.",
        "cache_after": True,
    }
    assert payload["inference_request"]["current_turn"]["operator_message"] == {
        "channel": "signal",
        "sender_e164": "+12025550100",
        "message_text": "hello",
        "approval_intent": None,
        "reaction_emoji": None,
        "quote_target_timestamp_ms": None,
        "reaction_target_timestamp_ms": None,
        "reply_to_proposal_token": None,
        "reaction_to_proposal_token": None,
    }
    assert "system_prompt" not in payload


def test_langfuse_plain_chat_observation_input_preserves_system_prompt() -> None:
    """Plain chat Langfuse input should include non-empty system prompts."""
    from services.effect.language import implementation as module

    payload = module._langfuse_chat_observation_input(
        system_prompt="Compress carefully.",
        prompt="hello",
        request_phase="initial",
    )

    assert payload == {
        "request_phase": "initial",
        "message": "hello",
        "system_prompt": "Compress carefully.",
    }


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
    service = DefaultLanguageService(
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
