"""Unit tests for the in-process LiteLLM adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import litellm
import pytest
from unittest.mock import MagicMock, call

from packages.brain_shared.language_model import (
    InferenceAssistantTextEvent,
    InferenceCache,
    InferenceMemoryContext,
    InferenceSystemBlock,
    InferenceToolCall,
    InferenceToolCallBatchEvent,
    InferenceToolDefinition,
    InferenceToolResult,
    InferenceToolResultBatchEvent,
    InferenceToolResultPayload,
    TextContentPart,
)
import resources.adapters.litellm.litellm_adapter as adapter_module
from resources.adapters.litellm.adapter import (
    AdapterChatMessage,
    AdapterDependencyError,
    AdapterInternalError,
    AdapterProviderCallAudit,
)
from resources.adapters.litellm.config import (
    LiteLlmAdapterSettings,
    LiteLlmProviderSettings,
)
from resources.adapters.litellm.litellm_adapter import LiteLlmLibraryAdapter
from tests.helpers.inference_request import make_inference_request


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


def _anthropic_settings() -> LiteLlmAdapterSettings:
    """Build deterministic adapter settings for Anthropic serializer coverage."""
    return LiteLlmAdapterSettings(
        timeout_seconds=9.0,
        max_retries=2,
        providers={
            "anthropic": LiteLlmProviderSettings(
                api_base="https://api.anthropic.com",
                options={"temperature": 0.0},
            )
        },
    )


def _openai_settings() -> LiteLlmAdapterSettings:
    """Build deterministic adapter settings for OpenAI serializer coverage."""
    return LiteLlmAdapterSettings(
        timeout_seconds=9.0,
        max_retries=2,
        providers={
            "openai": LiteLlmProviderSettings(
                api_base="https://api.openai.com/v1",
                options={"temperature": 0.0},
            )
        },
    )


def _gemini_settings() -> LiteLlmAdapterSettings:
    """Build deterministic adapter settings for Gemini serializer coverage."""
    return LiteLlmAdapterSettings(
        timeout_seconds=9.0,
        max_retries=2,
        providers={
            "gemini": LiteLlmProviderSettings(
                api_base="https://generativelanguage.googleapis.com",
                options={"temperature": 0.0},
            )
        },
    )


def _tool_inference_request(
    *,
    system_text: str = "Static context",
    user_text: str = "Find the resume",
    assistant_text: str = "Checking",
    tool_name: str = "demo-tool",
    tool_args: dict[str, object] | None = None,
    tool_result_text: str = "search results",
    cache_mode: str = "explicit",
) -> object:
    """Build one canonical inference request for adapter tool-chat tests."""
    return make_inference_request(
        system_blocks=(
            InferenceSystemBlock(
                kind="assistant_persona",
                text=system_text,
                cache_after=(cache_mode == "explicit"),
            ),
        ),
        memory_context=InferenceMemoryContext(
            current_focus=None,
            recent_conversation_summary="",
            recent_turns=(),
            reference_snippets=(),
        ),
        live_events=(
            InferenceAssistantTextEvent(text=assistant_text),
            InferenceToolCallBatchEvent(
                calls=(
                    InferenceToolCall(
                        call_id="call-1",
                        tool_name=tool_name,
                        arguments={} if tool_args is None else tool_args,
                    ),
                )
            ),
            InferenceToolResultBatchEvent(
                results=(
                    InferenceToolResult(
                        call_id="call-1",
                        tool_name=tool_name,
                        result=InferenceToolResultPayload(
                            mime_type="text/plain",
                            text=tool_result_text,
                        ),
                    ),
                )
            ),
        ),
        tools=(
            InferenceToolDefinition(
                name=tool_name,
                description="Do a thing.",
                input_schema={"type": "object"},
            ),
        ),
        cache=InferenceCache(mode=cache_mode),
        operator_message=make_inference_request().current_turn.operator_message.model_copy(
            update={"message_text": user_text}
        ),
    )


def _content_text(value: object) -> str:
    """Render one serialized provider content payload into plain text for assertions."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            str(item.get("text", "")) for item in value if isinstance(item, dict)
        )
    return str(value)


def test_load_prompt_file_reads_fallback_focus_template_from_disk() -> None:
    """Fallback prompt renderer should load authored focus wording from disk."""
    prompt = adapter_module._load_prompt_file(adapter_module._FOCUS_TEMPLATE_PATH)

    assert prompt == adapter_module._FOCUS_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert prompt == adapter_module._FOCUS_TEMPLATE
    assert "{{ text }}" in prompt


def test_render_content_parts_uses_file_backed_fallback_templates() -> None:
    """Fallback prompt wording should come from adapter prompt assets, not code."""
    rendered = adapter_module._render_content_parts(
        (
            adapter_module.FocusContentPart(text="focus"),
            adapter_module.ConversationSummaryContentPart(text="summary"),
            adapter_module.DialogueTurnContentPart(
                role="user",
                text="hello",
                is_summary=False,
            ),
            adapter_module.ReferenceSnippetContentPart(text="snippet"),
            adapter_module.OperatorMessageContentPart(
                channel="signal",
                sender_e164="+12025550100",
                message_text="ping",
                approval_intent=None,
                reaction_emoji=None,
                quote_target_timestamp_ms=None,
                reaction_target_timestamp_ms=None,
                reply_to_proposal_token=None,
                reaction_to_proposal_token=None,
            ),
        )
    )

    assert "<areas_of_focus>\nfocus\n</areas_of_focus>" in rendered
    assert (
        "<recent_conversation_summary>\nsummary\n</recent_conversation_summary>"
        in rendered
    )
    assert "<dialogue>\n- user: hello\n</dialogue>" in rendered
    assert "<reference_context>\n- snippet\n</reference_context>" in rendered
    assert "<operator_message>" in rendered
    assert "channel: signal" in rendered
    assert "sender: +12025550100" in rendered


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
        inference_request=make_inference_request(
            operator_message=make_inference_request().current_turn.operator_message.model_copy(
                update={"message_text": "hello"}
            ),
            tools=(
                InferenceToolDefinition(
                    name="demo-tool",
                    description="Do a thing.",
                    input_schema={"type": "object"},
                    strict_schema=True,
                ),
            ),
        ),
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
    assert result.raw_call is not None
    assert result.raw_call.request_api_base == "http://localhost:11434"
    assert result.raw_call.request_body is not None
    assert result.raw_call.request_body["model"] == "ollama/gpt-oss"
    assert result.raw_call.request_body["tool_choice"] == "auto"
    assert result.raw_call.request_body["parallel_tool_calls"] is True
    assert "hello" in _content_text(
        result.raw_call.request_body["messages"][-1]["content"]
    )
    assert result.raw_call.response_body == {
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


def test_chat_uses_anthropic_system_blocks_for_direct_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anthropic chat should serialize system prompt outside the messages array."""
    fake_module = _FakeLiteLlmModule()
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    adapter = LiteLlmLibraryAdapter(settings=_anthropic_settings())

    result = adapter.chat(
        provider="anthropic",
        model="claude-sonnet-4-6",
        system_prompt="You are Brain.",
        prompt="Hello",
    )

    assert result.text == "hello"
    assert fake_module.completion_calls[0]["model"] == "anthropic/claude-sonnet-4-6"
    assert fake_module.completion_calls[0]["system"] == [
        {"type": "text", "text": "You are Brain."}
    ]
    assert fake_module.completion_calls[0]["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Hello"}]}
    ]


def test_chat_with_tools_uses_openai_format_for_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anthropic tool chat should pass OpenAI-format messages and let LiteLLM translate."""
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
    adapter = LiteLlmLibraryAdapter(settings=_anthropic_settings())

    result = adapter.chat_with_tools(
        provider="anthropic",
        model="claude-sonnet-4-6",
        inference_request=_tool_inference_request(
            tool_args={"value": "x"},
            cache_mode="explicit",
        ),
    )

    assert result.finish_reason == "tool_call"
    assert fake_module.completion_calls[0]["system"] == [
        {
            "type": "text",
            "text": "Static context",
            "cache_control": {"type": "ephemeral"},
        },
    ]
    assert fake_module.completion_calls[0]["messages"][0]["role"] == "user"
    assert "Find the resume" in _content_text(
        fake_module.completion_calls[0]["messages"][0]["content"]
    )
    assert fake_module.completion_calls[0]["messages"][1] == {
        "role": "assistant",
        "content": "Checking",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "demo-tool",
                    "arguments": '{"value": "x"}',
                },
            }
        ],
    }
    assert fake_module.completion_calls[0]["messages"][2] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "search results",
    }
    assert fake_module.completion_calls[0]["tools"] == [
        {
            "name": "demo-tool",
            "input_schema": {"type": "object"},
            "description": "Do a thing.",
        }
    ]
    assert fake_module.completion_calls[0]["tool_choice"] == {"type": "auto"}
    assert "parallel_tool_calls" not in fake_module.completion_calls[0]


def test_lower_inference_request_for_anthropic_uses_litellm_compat_tool_messages() -> (
    None
):
    """Anthropic lowering should emit OpenAI-format tool messages for LiteLLM."""
    lowered = adapter_module._lower_inference_request_for_provider(
        provider="anthropic",
        inference_request=_tool_inference_request(
            tool_args={"value": "x"},
            cache_mode="explicit",
        ),
    )

    assert lowered.messages[0]["role"] == "user"
    assert lowered.messages[1] == {
        "role": "assistant",
        "content": "Checking",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "demo-tool",
                    "arguments": '{"value": "x"}',
                },
            }
        ],
    }
    assert lowered.messages[2] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "search results",
    }
    assert lowered.extra_kwargs["system"] == [
        {
            "type": "text",
            "text": "Static context",
            "cache_control": {"type": "ephemeral"},
        },
    ]


def test_anthropic_serializer_groups_adjacent_tool_results_immediately_after_tool_use() -> (
    None
):
    """Anthropic serializer must place tool_result blocks in the next user message."""
    messages, extra_kwargs = adapter_module._serialize_anthropic_messages(
        (
            AdapterChatMessage(
                role="system",
                content_parts=(TextContentPart(text="Static context"),),
            ),
            AdapterChatMessage(
                role="assistant",
                content_parts=(TextContentPart(text="Searching"),),
                tool_calls=(
                    adapter_module.AdapterChatToolCall(
                        tool_name="vault-search-files",
                        args_json='{"query":"Heidi"}',
                        tool_call_id="call-1",
                    ),
                ),
            ),
            AdapterChatMessage(
                role="tool",
                content_parts=(TextContentPart(text='{"items":[]}'),),
                tool_name="vault-search-files",
                tool_call_id="call-1",
            ),
            AdapterChatMessage(
                role="assistant",
                content_parts=(TextContentPart(text="No matches found."),),
            ),
        )
    )

    assert extra_kwargs["system"] == [{"type": "text", "text": "Static context"}]
    assert messages == [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Searching"},
                {
                    "type": "tool_use",
                    "id": "call-1",
                    "name": "vault-search-files",
                    "input": {"query": "Heidi"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-1",
                    "content": '{"items":[]}',
                }
            ],
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "No matches found."}],
        },
    ]


def test_anthropic_lowering_marks_error_tool_results() -> None:
    """Anthropic lowering should emit `is_error` when the IR marks a result as error."""
    lowered = adapter_module._serialize_anthropic_inference_messages(
        make_inference_request(
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
                            status="error",
                            is_error=True,
                            result=InferenceToolResultPayload(
                                mime_type="application/json",
                                data={"error": "not_found"},
                            ),
                        ),
                    )
                ),
            )
        )
    )

    assert lowered[2]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "call-1",
            "content": '{"error": "not_found"}',
            "is_error": True,
        }
    ]


def test_chat_uses_openai_native_content_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAI chat should use native message content arrays."""
    fake_module = _FakeLiteLlmModule()
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    adapter = LiteLlmLibraryAdapter(settings=_openai_settings())

    result = adapter.chat(
        provider="openai",
        model="gpt-5.4",
        system_prompt="You are Brain.",
        prompt="Hello",
    )

    assert result.text == "hello"
    assert fake_module.completion_calls[0]["model"] == "openai/gpt-5.4"
    assert fake_module.completion_calls[0]["messages"] == [
        {
            "role": "system",
            "content": [{"type": "text", "text": "You are Brain."}],
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": "Hello"}],
        },
    ]


def test_chat_with_tools_uses_openai_native_serializer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAI tool chat should use native content arrays and tool call messages."""
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
    adapter = LiteLlmLibraryAdapter(settings=_openai_settings())

    result = adapter.chat_with_tools(
        provider="openai",
        model="gpt-5.4",
        inference_request=make_inference_request(
            system_blocks=(
                InferenceSystemBlock(
                    kind="assistant_persona",
                    text="Static context",
                    cache_after=True,
                ),
            ),
            operator_message=make_inference_request().current_turn.operator_message.model_copy(
                update={"message_text": "Find the resume"}
            ),
            tools=(
                InferenceToolDefinition(
                    name="demo-tool",
                    description="Do a thing.",
                    input_schema={"type": "object"},
                    strict_schema=True,
                ),
            ),
            live_events=(
                InferenceAssistantTextEvent(text="Checking"),
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
            cache=InferenceCache(mode="explicit"),
        ),
    )

    assert result.finish_reason == "tool_call"
    assert fake_module.completion_calls[0]["messages"][0] == {
        "role": "system",
        "content": [{"type": "text", "text": "Static context"}],
    }
    assert "Find the resume" in _content_text(
        fake_module.completion_calls[0]["messages"][1]["content"]
    )
    assert fake_module.completion_calls[0]["messages"][2]["tool_calls"] == [
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "demo-tool",
                "arguments": '{"value": "x"}',
            },
        }
    ]
    assert fake_module.completion_calls[0]["messages"][3] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "search results",
    }
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
    assert fake_module.completion_calls[0]["tool_choice"] == "auto"
    assert fake_module.completion_calls[0]["parallel_tool_calls"] is True


def test_chat_uses_gemini_structured_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini chat should use structured message content arrays for LiteLLM conversion."""
    fake_module = _FakeLiteLlmModule()
    monkeypatch.setattr(adapter_module, "_load_litellm_module", lambda: fake_module)
    adapter = LiteLlmLibraryAdapter(settings=_gemini_settings())

    result = adapter.chat(
        provider="gemini",
        model="gemini-2.5-flash",
        system_prompt="You are Brain.",
        prompt="Hello",
    )

    assert result.text == "hello"
    assert fake_module.completion_calls[0]["model"] == "gemini/gemini-2.5-flash"
    assert fake_module.completion_calls[0]["messages"] == [
        {
            "role": "system",
            "content": [{"type": "text", "text": "You are Brain."}],
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": "Hello"}],
        },
    ]


def test_chat_with_tools_uses_gemini_structured_serializer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini tool chat should emit structured messages for LiteLLM's Gemini transform."""
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
    adapter = LiteLlmLibraryAdapter(settings=_gemini_settings())

    result = adapter.chat_with_tools(
        provider="gemini",
        model="gemini-2.5-flash",
        inference_request=_tool_inference_request(
            tool_args={"value": "x"},
            cache_mode="explicit",
        ),
    )

    assert result.finish_reason == "tool_call"
    assert fake_module.completion_calls[0]["messages"][0] == {
        "role": "system",
        "content": [{"type": "text", "text": "Static context"}],
    }
    assert "Find the resume" in _content_text(
        fake_module.completion_calls[0]["messages"][1]["content"]
    )
    assert fake_module.completion_calls[0]["messages"][2]["tool_calls"] == [
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "demo-tool",
                "arguments": '{"value": "x"}',
            },
        }
    ]
    assert fake_module.completion_calls[0]["messages"][3] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "search results",
    }
    assert fake_module.completion_calls[0]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "demo-tool",
                "description": "Do a thing.",
                "parameters": {"type": "object"},
            },
        }
    ]
    assert fake_module.completion_calls[0]["tool_choice"] == "auto"
    assert fake_module.completion_calls[0]["parallel_tool_calls"] is True


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
            inference_request=make_inference_request(
                tools=(
                    InferenceToolDefinition(
                        name="demo-tool",
                        description="Do a thing.",
                        input_schema={"type": "object"},
                    ),
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
            inference_request=make_inference_request(
                tools=(
                    InferenceToolDefinition(
                        name="demo-tool",
                        description="Do a thing.",
                        input_schema={"type": "object"},
                    ),
                ),
            ),
        )

    raw_call = exc_info.value.raw_call
    assert raw_call is not None
    assert raw_call.request_body["model"] == "ollama/gpt-oss"
    assert raw_call.request_body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "demo-tool",
                "description": "Do a thing.",
                "parameters": {"type": "object"},
            },
        }
    ]
    assert raw_call.request_body["tool_choice"] == "auto"
    assert raw_call.request_body["parallel_tool_calls"] is True
    assert "hello" in _content_text(raw_call.request_body["messages"][-1]["content"])
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
