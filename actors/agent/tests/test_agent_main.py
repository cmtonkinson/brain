"""Behavior tests for the Brain Agent process entrypoint."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from packages.brain_shared.language_model import (
    ConversationSummaryContentPart,
    DialogueTurnContentPart,
    FocusContentPart,
    InferenceAssistantTextEvent,
    InferenceCurrentTurn,
    InferenceMemoryContext,
    InferenceMeta,
    InferenceOperatorMessage,
    InferenceParallelToolCalls,
    InferenceRequest,
    InferenceSystem,
    InferenceSystemBlock,
    InferenceToolCall,
    InferenceToolCallBatchEvent,
    InferenceToolChoice,
    InferenceToolDefinition,
    InferenceToolExecutionHints,
    InferenceToolResult,
    InferenceToolResultBatchEvent,
    InferenceToolResultPayload,
    OperatorMessageContentPart,
    ReferenceSnippetContentPart,
)
from packages.brain_sdk import (
    BrainDependencyError,
    BrainInternalError,
    BrainNotFoundError,
    BrainPolicyError,
    BrainTransportError,
    CapabilityDescriptor,
    CapabilitySearchHit,
    LmsChatToolCall,
    LmsToolChatResult,
    MemoryContextBlock,
    MemoryDialogueTurn,
    MemorySessionRef,
    SwitchboardOperatorInstruction,
)
from packages.brain_sdk.errors import SdkErrorDetail


def _actor_settings_stub(**agent_overrides):
    agent_defaults = {
        "session_start_mode": "existing",
        "personality": "default",
        "operator_profile": "Refer to me as 'boss'",
        "system_prompt_append": "",
        "source": "agent",
        "principal": "operator",
        "capability_discovery_deny_list": (),
        "tool_return_compress_threshold": 4000,
        "tool_return_max_chars": 8000,
        "tool_loop_tier2_hop_threshold": 3,
    }
    agent_defaults.update(agent_overrides)
    return SimpleNamespace(
        logging=SimpleNamespace(
            level="INFO",
            file_capture_enabled=False,
            file_capture_level="VERBOSE",
            file_capture_directory="logs",
            json_output=True,
            process_name="agent",
            environment="dev",
        ),
        agent=SimpleNamespace(**agent_defaults),
    )


def _core_settings_stub(personality: str = "default", system_prompt_append: str = ""):
    return SimpleNamespace(
        profile=SimpleNamespace(
            personality=personality,
            operator=SimpleNamespace(profile_context="Refer to me as 'boss'"),
            system_prompt_append=system_prompt_append,
        )
    )


def test_resolve_config_path_uses_env_override(monkeypatch) -> None:
    """Config-path helper should return a Path only when the env var is set."""
    from actors.agent import main

    monkeypatch.setenv("BRAIN_ACTORS_CONFIG_FILE", "/tmp/actors.yaml")

    assert main._resolve_config_path() == Path("/tmp/actors.yaml")


def test_resolve_core_config_path_uses_env_override(monkeypatch) -> None:
    """Core-config helper should return a Path only when the env var is set."""
    from actors.agent import main

    monkeypatch.setenv("BRAIN_CORE_CONFIG_FILE", "/tmp/core.yaml")

    assert main._resolve_core_config_path() == Path("/tmp/core.yaml")


def test_resolve_resources_config_path_uses_env_override(monkeypatch) -> None:
    """Resources-config helper should return a Path only when the env var is set."""
    from actors.agent import main

    monkeypatch.setenv("BRAIN_RESOURCES_CONFIG_FILE", "/tmp/resources.yaml")

    assert main._resolve_resources_config_path() == Path("/tmp/resources.yaml")


def test_load_startup_settings_passes_explicit_config_paths(monkeypatch) -> None:
    """Startup settings loader should honor actor/core/resources env path overrides."""
    from actors.agent import main

    actor_calls: list[Path | None] = []
    runtime_calls: list[tuple[Path | None, Path | None]] = []

    def _fake_load_actor_settings(*, config_path=None, **_kwargs):
        actor_calls.append(config_path)
        return "actors"

    def _fake_load_core_runtime_settings(
        *, core_config_path=None, resources_config_path=None, **_kwargs
    ):
        runtime_calls.append((core_config_path, resources_config_path))
        return "runtime"

    monkeypatch.setenv("BRAIN_ACTORS_CONFIG_FILE", "/tmp/actors.yaml")
    monkeypatch.setenv("BRAIN_CORE_CONFIG_FILE", "/tmp/core.yaml")
    monkeypatch.setenv("BRAIN_RESOURCES_CONFIG_FILE", "/tmp/resources.yaml")
    monkeypatch.setattr(main, "load_actor_settings", _fake_load_actor_settings)
    monkeypatch.setattr(
        main, "load_core_runtime_settings", _fake_load_core_runtime_settings
    )

    settings, runtime = main._load_startup_settings()

    assert settings == "actors"
    assert runtime == "runtime"
    assert actor_calls == [Path("/tmp/actors.yaml")]
    assert runtime_calls == [(Path("/tmp/core.yaml"), Path("/tmp/resources.yaml"))]


def test_resolve_heartbeat_path_uses_default_when_env_missing(monkeypatch) -> None:
    """Heartbeat-path helper should default to the runtime heartbeat path."""
    from actors.agent import main

    monkeypatch.delenv("BRAIN_AGENT_HEARTBEAT_FILE", raising=False)

    assert main._resolve_heartbeat_path() == Path("/run/brain/agent-heartbeat")


def test_resolve_heartbeat_path_uses_env_override(monkeypatch) -> None:
    """Heartbeat-path helper should accept an explicit env override."""
    from actors.agent import main

    monkeypatch.setenv("BRAIN_AGENT_HEARTBEAT_FILE", "/tmp/agent-heartbeat")

    assert main._resolve_heartbeat_path() == Path("/tmp/agent-heartbeat")


def test_write_heartbeat_creates_parent_and_updates_file(tmp_path) -> None:
    """Heartbeat writer should create missing parents and touch the target file."""
    from actors.agent import main

    heartbeat_path = tmp_path / "run" / "brain" / "agent-heartbeat"

    main._write_heartbeat(path=heartbeat_path)

    assert heartbeat_path.exists()


def test_render_system_prompt_returns_rendered_default_personality() -> None:
    """render_system_prompt should render the default personality template."""
    from packages.brain_sdk.personality import (
        _SYSTEM_PROMPT_TEMPLATE_PATH,
        render_system_prompt,
    )

    template = _SYSTEM_PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "{{ personality }}" in template
    assert "system_prompt_append" in template

    prompt = render_system_prompt(
        "default",
        operator_profile="Refer to me as 'boss'",
        system_prompt_append="Appendix",
    )

    assert prompt != ""
    assert "tool" in prompt.lower()
    assert "Brain" in prompt
    assert "Refer to me as 'boss'" in prompt
    assert "Appendix" in prompt
    assert "system_prompt_append" not in prompt


def test_render_system_prompt_template_rejects_unresolved_placeholders() -> None:
    """System prompt template renderer should reject unresolved double-brace vars."""
    from packages.brain_sdk.personality import _render_template

    try:
        _render_template(
            "Hello {{ personality }} {{ missing }}",
            personality="Brain",
        )
        assert False, "expected unresolved placeholder validation"
    except ValueError as exc:
        assert "missing" in str(exc)


def test_render_system_prompt_template_supports_spaced_and_unspaced_placeholders() -> (
    None
):
    """System prompt template renderer should accept both brace-spacing styles."""
    from packages.brain_sdk.personality import _render_template

    rendered = _render_template(
        "A={{personality}} B={{ personality }} C={{system_prompt_append}} D={{ system_prompt_append }}",
        personality="Brain",
        system_prompt_append="tail",
    )

    assert rendered == "A=Brain B=Brain C=tail D=tail"


def test_render_system_prompt_raises_for_unknown_personality() -> None:
    """render_system_prompt should raise PersonalityNotFoundError for unknown names."""
    from packages.brain_sdk.personality import (
        PersonalityNotFoundError,
        render_system_prompt,
    )

    try:
        render_system_prompt("nonexistent_personality_xyz")
        assert False, "expected PersonalityNotFoundError"
    except PersonalityNotFoundError:
        pass


def test_load_prompt_file_reads_compressor_prompt_from_disk() -> None:
    """Prompt-file helper should load the colocated compressor prompt text."""
    from actors.agent import main

    prompt = main._load_prompt_file(main._COMPRESS_SYSTEM_PROMPT_PATH)

    assert prompt == main._COMPRESS_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    assert prompt == main._COMPRESS_SYSTEM_PROMPT
    assert "tool result compressor" in prompt.lower()


def test_load_prompt_file_reads_compressor_user_template_from_disk() -> None:
    """Prompt-file helper should load the colocated compressor user template."""
    from actors.agent import main

    prompt = main._load_prompt_file(main._COMPRESS_USER_PROMPT_TEMPLATE_PATH)

    assert prompt == main._COMPRESS_USER_PROMPT_TEMPLATE_PATH.read_text(
        encoding="utf-8"
    )
    assert prompt == main._COMPRESS_USER_PROMPT_TEMPLATE
    assert "{{tool_name}}" in prompt
    assert "{{raw_output}}" in prompt


def test_render_prompt_template_replaces_named_placeholders() -> None:
    """Prompt renderer should replace each named placeholder verbatim."""
    from actors.agent import main

    rendered = main._render_prompt_template(
        "Tool: {{tool_name}}\nRaw output:\n{{raw_output}}",
        tool_name="vault-search-files",
        raw_output='{"items":[]}',
    )

    assert rendered == 'Tool: vault-search-files\nRaw output:\n{"items":[]}'


def test_render_prompt_template_raises_for_unresolved_placeholders() -> None:
    """Prompt renderer should fail when a placeholder remains unresolved."""
    from actors.agent import main

    try:
        main._render_prompt_template("Tool: {{tool_name}}\nMode: {{call_mode}}")
        assert False, "expected unresolved placeholder validation"
    except ValueError as exc:
        assert "call_mode" in str(exc)


def test_load_agent_context_properties_reads_json_from_disk() -> None:
    """Agent context schema helper should load the colocated JSON object."""
    from actors.agent import main

    properties = main._load_agent_context_properties()

    assert properties == main._AGENT_CONTEXT_PROPERTIES
    assert set(properties) == {"call_mode", "response_detail"}


def test_configure_logging_uses_shared_dual_path_settings(monkeypatch) -> None:
    """Logging helper should delegate to shared logging with actor settings."""
    from actors.agent import main

    configure_logging = MagicMock()
    monkeypatch.setattr(
        "packages.brain_shared.logging.configure_logging", configure_logging
    )

    settings = _actor_settings_stub()
    settings.logging.level = "DEBUG"
    settings.logging.file_capture_enabled = True
    settings.logging.file_capture_level = "VERBOSE"
    settings.logging.file_capture_directory = "logs"
    settings.logging.json_output = False
    settings.logging.process_name = "brain-agent"
    settings.logging.environment = "dev"

    main._configure_logging(settings=settings)

    configure_logging.assert_called_once_with(
        level="DEBUG",
        file_capture_enabled=True,
        file_capture_level="VERBOSE",
        file_capture_directory="logs",
        json_output=False,
        process_name="brain-agent",
        environment="dev",
    )


def test_build_inference_request_translates_tool_loop_history() -> None:
    """Inference-request assembly should preserve tool loop state as live events."""
    from actors.agent import main
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        SystemPromptPart,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    messages = [
        ModelRequest(parts=[SystemPromptPart("system"), UserPromptPart("hello")]),
        ModelResponse(
            parts=[
                TextPart("checking"),
                ToolCallPart(
                    tool_name="vault-get-file",
                    args={"input_payload": {"file_path": "resume.md"}},
                    tool_call_id="call-1",
                ),
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="vault-get-file",
                    content={"path": "resume.md"},
                    tool_call_id="call-1",
                )
            ]
        ),
    ]

    result = main._build_inference_request(
        session_id="session-1",
        source="agent",
        principal="operator",
        meta=None,
        system_blocks=(InferenceSystemBlock(kind="assistant_persona", text="system"),),
        messages=messages,
        tool_defs=[],
        allow_text_output=True,
        profile="standard",
        tool_requires_approval={},
    )

    assert result == InferenceRequest(
        meta=InferenceMeta(
            trace_id="",
            session_id="session-1",
            source="agent",
            principal="operator",
            envelope_id="",
            parent_id="",
        ),
        system=InferenceSystem(
            blocks=(InferenceSystemBlock(kind="assistant_persona", text="system"),)
        ),
        memory_context=InferenceMemoryContext(
            current_focus=None,
            recent_conversation_summary="",
            recent_turns=(),
            reference_snippets=(),
        ),
        current_turn=InferenceCurrentTurn(
            operator_message=InferenceOperatorMessage(
                channel="",
                sender_e164="",
                message_text="hello",
            )
        ),
        tools=(),
        live_events=(
            InferenceAssistantTextEvent(text="checking"),
            InferenceToolCallBatchEvent(
                calls=(
                    InferenceToolCall(
                        call_id="call-1",
                        tool_name="vault-get-file",
                        arguments={"input_payload": {"file_path": "resume.md"}},
                    ),
                )
            ),
            InferenceToolResultBatchEvent(
                results=(
                    InferenceToolResult(
                        call_id="call-1",
                        tool_name="vault-get-file",
                        status="success",
                        is_error=False,
                        result=InferenceToolResultPayload(
                            mime_type="application/json",
                            data={"path": "resume.md"},
                        ),
                    ),
                )
            ),
        ),
        controls=main.InferenceControls(
            allow_text_output=True,
            tool_choice=InferenceToolChoice(mode="auto"),
            parallel_tool_calls=InferenceParallelToolCalls(mode="allow"),
            profile="standard",
        ),
        cache=main.InferenceCache(mode="none"),
    )


def test_build_inference_request_marks_explicit_cache_mode() -> None:
    """Prompt-cache markers should become explicit cache intent in the IR."""
    from actors.agent import main
    from pydantic_ai.messages import CachePoint, ModelRequest, UserPromptPart

    messages = [
        ModelRequest(parts=[UserPromptPart(content=["hello", CachePoint()])]),
        ModelRequest(parts=[UserPromptPart(content=[CachePoint()])]),
    ]

    result = main._build_inference_request(
        session_id="session-1",
        source="agent",
        principal="operator",
        meta=None,
        system_blocks=(),
        messages=messages,
        tool_defs=[],
        allow_text_output=True,
        profile="standard",
        tool_requires_approval={},
    )

    assert result.current_turn.operator_message.message_text == "hello"
    assert result.cache.mode == "explicit"


def test_build_inference_request_batches_tool_returns_and_sets_status() -> None:
    """Tool returns from one request should become one batch with explicit statuses."""
    from actors.agent import main
    from pydantic_ai.messages import ModelRequest, ToolReturnPart

    messages = [
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="vault-search-files",
                    content="",
                    tool_call_id="call-empty",
                ),
                ToolReturnPart(
                    tool_name="vault-get-file",
                    content={
                        "error": "not_found",
                        "message": "missing",
                        "capability_id": "vault-get-file",
                    },
                    tool_call_id="call-error",
                ),
            ]
        )
    ]

    result = main._build_inference_request(
        session_id="session-1",
        source="agent",
        principal="operator",
        meta=None,
        system_blocks=(),
        messages=messages,
        tool_defs=[],
        allow_text_output=True,
        profile="standard",
        tool_requires_approval={},
    )

    assert result.live_events == (
        InferenceToolResultBatchEvent(
            results=(
                InferenceToolResult(
                    call_id="call-empty",
                    tool_name="vault-search-files",
                    status="empty",
                    is_error=False,
                    result=InferenceToolResultPayload(
                        mime_type="text/plain",
                        text="",
                    ),
                ),
                InferenceToolResult(
                    call_id="call-error",
                    tool_name="vault-get-file",
                    status="error",
                    is_error=True,
                    result=InferenceToolResultPayload(
                        mime_type="application/json",
                        data={
                            "error": "not_found",
                            "message": "missing",
                            "capability_id": "vault-get-file",
                        },
                    ),
                ),
            )
        ),
    )


def test_build_inference_request_assigns_cache_marker_to_tool_result_batch() -> None:
    """Cache-only prompts after tool returns should mark the tool-result batch itself."""
    from actors.agent import main
    from pydantic_ai.messages import (
        CachePoint,
        ModelRequest,
        ModelResponse,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    messages = [
        ModelRequest(parts=[UserPromptPart(content="hello")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="search_tools",
                    args={"query": "notify"},
                    tool_call_id="call-1",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="search_tools",
                    content='{"tool_id":"attention-notify"}',
                    tool_call_id="call-1",
                ),
                UserPromptPart(content=[CachePoint()]),
            ]
        ),
    ]

    result = main._build_inference_request(
        session_id="session-1",
        source="agent",
        principal="operator",
        meta=None,
        system_blocks=(),
        messages=messages,
        tool_defs=[],
        allow_text_output=True,
        profile="standard",
        tool_requires_approval={},
    )

    assert result.live_events == (
        InferenceToolCallBatchEvent(
            calls=(
                InferenceToolCall(
                    call_id="call-1",
                    tool_name="search_tools",
                    arguments={"query": "notify"},
                ),
            )
        ),
        InferenceToolResultBatchEvent(
            results=(
                InferenceToolResult(
                    call_id="call-1",
                    tool_name="search_tools",
                    status="success",
                    is_error=False,
                    result=InferenceToolResultPayload(
                        mime_type="text/plain",
                        text='{"tool_id":"attention-notify"}',
                    ),
                ),
            ),
            cache_after=True,
        ),
    )


def test_history_processor_adds_rolling_cachepoint_for_high_value_growth() -> None:
    """Large exploratory tool-result growth should earn a rolling cachepoint."""
    from actors.agent import main
    from pydantic_ai.messages import (
        CachePoint,
        ModelRequest,
        ModelResponse,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    processor = main._build_history_processor(
        client=object(),  # type: ignore[arg-type]
        timeout_seconds=None,
        compress_threshold=10_000,
        max_chars=20_000,
        tier2_hop_threshold=1,
    )
    messages = [
        ModelRequest(parts=[UserPromptPart(content=["hello", CachePoint()])]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="search_tools",
                    args={
                        "query": "find person",
                        "call_mode": "explore",
                        "response_detail": "Orient before choosing a concrete vault tool.",
                    },
                    tool_call_id="call-1",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="search_tools",
                    content="x" * 8000,
                    tool_call_id="call-1",
                )
            ]
        ),
    ]

    processed = asyncio.run(processor(None, messages))

    assert isinstance(processed[-1], ModelRequest)
    assert isinstance(processed[-1].parts[-1], UserPromptPart)
    assert processed[-1].parts[-1].content == [CachePoint()]


def test_history_processor_skips_rolling_cachepoint_for_low_value_growth() -> None:
    """Small decisive successful results should not pay the rolling-cache premium."""
    from actors.agent import main
    from pydantic_ai.messages import (
        CachePoint,
        ModelRequest,
        ModelResponse,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    processor = main._build_history_processor(
        client=object(),  # type: ignore[arg-type]
        timeout_seconds=None,
        compress_threshold=10_000,
        max_chars=20_000,
        tier2_hop_threshold=1,
    )
    messages = [
        ModelRequest(parts=[UserPromptPart(content=["hello", CachePoint()])]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="vault-get-file",
                    args={
                        "file_path": "entities/people/heidi.md",
                        "call_mode": "decide",
                        "response_detail": "Read one specific entity file.",
                    },
                    tool_call_id="call-1",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="vault-get-file",
                    content="ok",
                    tool_call_id="call-1",
                )
            ]
        ),
    ]

    processed = asyncio.run(processor(None, messages))

    assert isinstance(processed[-1], ModelRequest)
    assert not any(
        isinstance(part, UserPromptPart) and part.content == [CachePoint()]
        for part in processed[-1].parts
    )


def test_format_user_prompt_places_cachepoint_before_current_instruction() -> None:
    """The operator-message block should come after the historical snapshot cache cut."""
    from actors.agent import main
    from pydantic_ai.messages import CachePoint

    prompt = main._format_user_prompt(
        instruction=SwitchboardOperatorInstruction(
            sender_e164="+12025550100",
            message_text="hello",
            timestamp_ms=1,
            source_device="1",
            source="signal",
            group_id=None,
            quote_target_timestamp_ms=None,
            reaction_target_timestamp_ms=None,
            reaction_emoji=None,
            approval_intent=None,
        ),
        context=MemoryContextBlock(
            current_focus="current focus",
            recent_conversation_summary="prior summary",
            recent_turns=(
                MemoryDialogueTurn(
                    role="assistant",
                    content="prior turn",
                    is_summary=False,
                ),
            ),
            reference_snippets=("snippet",),
        ),
    )

    cache_index = next(
        index for index, item in enumerate(prompt) if isinstance(item, CachePoint)
    )
    assert cache_index == 2
    assert prompt[0] == FocusContentPart(text="current focus")
    assert prompt[1] == ConversationSummaryContentPart(text="prior summary")
    assert prompt[3] == DialogueTurnContentPart(
        role="assistant",
        text="prior turn",
        is_summary=False,
    )
    assert prompt[4] == ReferenceSnippetContentPart(text="snippet")
    assert prompt[5] == OperatorMessageContentPart(
        channel="signal",
        sender_e164="+12025550100",
        message_text="hello",
        approval_intent=None,
        reaction_emoji=None,
        quote_target_timestamp_ms=None,
        reaction_target_timestamp_ms=None,
        reply_to_proposal_token=None,
        reaction_to_proposal_token=None,
    )


def test_normalize_tool_return_passes_through_small_results_and_logs() -> None:
    """Small tool returns should bypass compression but still emit audit metadata."""
    from actors.agent import main

    debug = MagicMock()
    original_debug = main._LOGGER.debug
    main._LOGGER.debug = debug
    try:
        normalized = asyncio.run(
            main._normalize_tool_return(
                client=object(),  # type: ignore[arg-type]
                tool_name="vault-get-file",
                tool_call_id="call-1",
                tool_args={"file_path": "notes/test.md", "call_mode": "decide"},
                raw_content="hello",
                compress_threshold=10,
                max_chars=20,
            )
        )
    finally:
        main._LOGGER.debug = original_debug

    assert normalized == main._NormalizedToolReturn(
        content="hello",
        normalization_kind="pass_through",
        raw_content="hello",
        raw_char_count=5,
        final_char_count=5,
    )
    debug.assert_called_once()
    assert debug.call_args.kwargs["extra"] == {
        "tool_name": "vault-get-file",
        "tool_call_id": "call-1",
        "tool_input": {"file_path": "notes/test.md", "call_mode": "decide"},
        "raw_output": "hello",
        "display_output": "hello",
        "normalization_kind": "pass_through",
        "raw_char_count": 5,
        "final_char_count": 5,
        "compressed_by_model": "",
        "compressed_by_provider": "",
    }


def test_normalize_tool_return_compresses_decide_mode_results() -> None:
    """Large decide-mode tool returns should be compressed before reuse."""
    from actors.agent import main

    async def _fake_compress_tool_return(**kwargs):
        assert kwargs["tool_name"] == "vault-search-files"
        assert kwargs["call_mode"] == "decide"
        assert kwargs["response_detail"] == "Find Claire's birthday."
        assert kwargs["raw_content"] == "x" * 40
        return main._CompressedToolReturn(
            content="compressed birthday",
            model="claude-haiku-4-5-20251001",
            provider="anthropic",
        )

    debug = MagicMock()
    original_compress = main._compress_tool_return
    original_debug = main._LOGGER.debug
    main._compress_tool_return = _fake_compress_tool_return  # type: ignore[assignment]
    main._LOGGER.debug = debug
    try:
        normalized = asyncio.run(
            main._normalize_tool_return(
                client=object(),  # type: ignore[arg-type]
                tool_name="vault-search-files",
                tool_call_id="call-2",
                tool_args={
                    "query": "Claire birthday",
                    "call_mode": "decide",
                    "response_detail": "Find Claire's birthday.",
                },
                raw_content="x" * 40,
                compress_threshold=10,
                max_chars=20,
            )
        )
    finally:
        main._compress_tool_return = original_compress  # type: ignore[assignment]
        main._LOGGER.debug = original_debug

    assert normalized == main._NormalizedToolReturn(
        content="compressed birthday",
        normalization_kind="compress",
        raw_content="x" * 40,
        raw_char_count=40,
        final_char_count=len("compressed birthday"),
        compressed_by_model="claude-haiku-4-5-20251001",
        compressed_by_provider="anthropic",
    )
    debug.assert_called_once()
    assert debug.call_args.kwargs["extra"]["normalization_kind"] == "compress"
    assert debug.call_args.kwargs["extra"]["compressed_by_model"] == (
        "claude-haiku-4-5-20251001"
    )


def test_normalize_tool_return_truncates_large_explore_results() -> None:
    """Large explore-mode tool returns should truncate without LLM compression."""
    from actors.agent import main

    debug = MagicMock()
    original_debug = main._LOGGER.debug
    main._LOGGER.debug = debug
    try:
        normalized = asyncio.run(
            main._normalize_tool_return(
                client=object(),  # type: ignore[arg-type]
                tool_name="vault-list-files",
                tool_call_id="call-3",
                tool_args={"path": "/", "call_mode": "explore"},
                raw_content="abcdefghijklmnopqrstuvwxyz",
                compress_threshold=10,
                max_chars=8,
            )
        )
    finally:
        main._LOGGER.debug = original_debug

    assert normalized == main._NormalizedToolReturn(
        content="abcdefgh\n[truncated]",
        normalization_kind="truncate",
        raw_content="abcdefghijklmnopqrstuvwxyz",
        raw_char_count=26,
        final_char_count=len("abcdefgh\n[truncated]"),
    )
    debug.assert_called_once()
    assert debug.call_args.kwargs["extra"]["normalization_kind"] == "truncate"


def test_compress_tool_return_uses_file_backed_user_template() -> None:
    """Compression call should render the editable prompt template into LMS input."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.system_prompt: str | None = None
            self.prompt: str | None = None
            self.profile: str | None = None

        def lms_chat(
            self,
            *,
            system_prompt: str = "",
            prompt: str,
            profile: str = "standard",
            timeout_seconds: float | None = None,
        ):
            assert timeout_seconds is None
            self.system_prompt = system_prompt
            self.prompt = prompt
            self.profile = profile
            return type(
                "ChatResult",
                (),
                {
                    "text": "compressed result",
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                },
            )()

    client = _FakeClient()
    result = asyncio.run(
        main._compress_tool_return(
            client=client,  # type: ignore[arg-type]
            tool_name="vault-search-files",
            call_mode="decide",
            response_detail="Find Claire's birthday.",
            raw_content='{"items":[]}',
            max_chars=400,
        )
    )

    assert result == main._CompressedToolReturn(
        content="compressed result",
        model="claude-haiku-4-5-20251001",
        provider="anthropic",
    )
    assert client.profile == "quick"
    assert client.system_prompt == main._COMPRESS_SYSTEM_PROMPT
    assert client.prompt == main._render_prompt_template(
        main._COMPRESS_USER_PROMPT_TEMPLATE,
        tool_name="vault-search-files",
        call_mode="decide",
        intent="Find Claire's birthday.",
        raw_output='{"items":[]}',
    )


def test_create_runtime_uses_personality_system_prompt() -> None:
    """Runtime creation should render the personality and use it as the system prompt."""
    from actors.agent import main

    class _FakeClient:
        def memory_create_session(self):
            return MemorySessionRef(session_id="session-1")

        def memory_get_latest_or_create_session(self):
            return MemorySessionRef(session_id="session-1")

        def describe_capabilities(self):
            return ()

        def list_always_on_capabilities(self):
            return ()

    runtime = main._create_runtime(
        client=_FakeClient(),
        settings=_actor_settings_stub(personality="default"),
    )

    assert any(
        "Brain" in str(item)
        for item in runtime.agent._system_prompts  # pyright: ignore[reportPrivateUsage]
    )


def test_create_runtime_includes_system_prompt_append_in_prompt_and_blocks() -> None:
    """Runtime creation should preserve agent.system_prompt_append in both prompt forms."""
    from actors.agent import main

    class _FakeClient:
        def memory_create_session(self):
            return MemorySessionRef(session_id="session-1")

        def memory_get_latest_or_create_session(self):
            return MemorySessionRef(session_id="session-1")

        def describe_capabilities(self):
            return ()

        def list_always_on_capabilities(self):
            return ()

    append_text = "APPEND_MARKER_123"
    runtime = main._create_runtime(
        client=_FakeClient(),
        settings=_actor_settings_stub(system_prompt_append=append_text),
    )

    assert any(
        append_text in str(item)
        for item in runtime.agent._system_prompts  # pyright: ignore[reportPrivateUsage]
    )
    assert any(
        append_text in block.text
        for block in runtime.model._system_blocks  # pyright: ignore[reportPrivateUsage]
    )


def test_create_runtime_uses_configured_tier2_hop_threshold() -> None:
    """Runtime creation should wire the configured Tier 2 hop threshold."""
    from actors.agent import main

    class _FakeClient:
        def memory_create_session(self):
            return MemorySessionRef(session_id="session-1")

        def memory_get_latest_or_create_session(self):
            return MemorySessionRef(session_id="session-1")

        def describe_capabilities(self):
            return ()

        def list_always_on_capabilities(self):
            return ()

    captured: dict[str, object] = {}

    def _fake_build_history_processor(**kwargs):
        captured.update(kwargs)

        async def _processor(_ctx, messages):
            return messages

        return _processor

    settings = _actor_settings_stub()
    settings.agent.tool_loop_tier2_hop_threshold = 5
    original = main._build_history_processor
    main._build_history_processor = _fake_build_history_processor  # type: ignore[assignment]
    try:
        main._create_runtime(
            client=_FakeClient(),
            settings=settings,
        )
    finally:
        main._build_history_processor = original  # type: ignore[assignment]

    assert captured["tier2_hop_threshold"] == 5


def test_build_capability_tools_invokes_sdk_client() -> None:
    """Capability tool wrappers should route tool calls through Brain SDK only."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object], str, str, str, str]] = []

        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
            reply_to_proposal_token: str = "",
            reaction_to_proposal_token: str = "",
        ):
            self.calls.append(
                (
                    capability_id,
                    input_payload,
                    actor,
                    channel,
                    reply_to_proposal_token,
                    reaction_to_proposal_token,
                )
            )
            return type("InvokeResult", (), {"output": {"ok": True}})()

    client = _FakeClient()
    turn_state = main._TurnState(actor="operator", channel="signal")
    tools = main._build_capability_tools(
        client=client,  # type: ignore[arg-type]
        capabilities=(
            CapabilityDescriptor(
                capability_id="demo-tool",
                kind="native_op",
                version="1.0.0",
                summary="Do the thing.",
                input_schema={"value": "string"},
                output_schema={"ok": "boolean"},
                autonomy=0,
                requires_approval=False,
                side_effects=(),
                required_capabilities=(),
            ),
        ),
        turn_state=turn_state,
    )

    result = tools[0].function(value="x")

    assert result == {"ok": True}
    assert client.calls == [("demo-tool", {"value": "x"}, "operator", "signal", "", "")]


def test_build_capability_tools_uses_descriptor_input_schema() -> None:
    """Capability tool wrappers should advertise the CES input schema directly."""
    from actors.agent import main

    class _FakeClient:
        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
            reply_to_proposal_token: str = "",
            reaction_to_proposal_token: str = "",
        ):
            del (
                capability_id,
                input_payload,
                actor,
                channel,
                reply_to_proposal_token,
                reaction_to_proposal_token,
            )
            return type("InvokeResult", (), {"output": {"ok": True}})()

    tools = main._build_capability_tools(
        client=_FakeClient(),  # type: ignore[arg-type]
        capabilities=(
            CapabilityDescriptor(
                capability_id="vault-get-file",
                kind="native_op",
                version="1.0.0",
                summary="Read one markdown file by path.",
                input_schema={
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                    "additionalProperties": False,
                },
                output_schema={"type": "object"},
                autonomy=0,
                requires_approval=False,
                side_effects=(),
                required_capabilities=(),
            ),
        ),
        turn_state=main._TurnState(actor="operator", channel="signal"),
    )

    assert tools[0].tool_def.parameters_json_schema == {
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
        "additionalProperties": False,
    }


def test_build_capability_tools_returns_policy_denial_payload() -> None:
    """Approval-gated denials should return tool data instead of aborting the turn."""
    from actors.agent import main

    class _FakeClient:
        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
            reply_to_proposal_token: str = "",
            reaction_to_proposal_token: str = "",
        ):
            del (
                capability_id,
                input_payload,
                actor,
                channel,
                reply_to_proposal_token,
                reaction_to_proposal_token,
            )
            raise BrainPolicyError(
                message=(
                    "capabilities.invoke domain failure: "
                    "policy denied capability invocation"
                ),
                operation="capabilities.invoke",
                details=(
                    SdkErrorDetail(
                        code="permission_denied",
                        message="policy denied capability invocation",
                        category="policy",
                        metadata={
                            "proposal_token": "tok-123",
                            "reason_codes": "approval_required",
                        },
                    ),
                ),
            )

    tools = main._build_capability_tools(
        client=_FakeClient(),  # type: ignore[arg-type]
        capabilities=(
            CapabilityDescriptor(
                capability_id="vault-move-path",
                kind="native_op",
                version="1.0.0",
                summary="Move one file or directory path.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                autonomy=0,
                requires_approval=True,
                side_effects=("writes_vault",),
                required_capabilities=(),
            ),
        ),
        turn_state=main._TurnState(actor="operator", channel="signal"),
    )

    result = tools[0].function(
        source_path="notes/old.md",
        target_path="notes/new.md",
    )

    assert result == {
        "error": "policy_denied",
        "message": (
            "capabilities.invoke domain failure: policy denied capability invocation"
        ),
        "capability_id": "vault-move-path",
        "requires_approval": True,
        "proposal_token": "tok-123",
        "proposal_expires_at": "",
        "reason_codes": ["approval_required"],
    }


def test_build_capability_tools_returns_not_found_payload() -> None:
    """Not-found domain failures should be returned as structured tool data."""
    from actors.agent import main

    class _FakeClient:
        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
            reply_to_proposal_token: str = "",
            reaction_to_proposal_token: str = "",
        ):
            del (
                capability_id,
                input_payload,
                actor,
                channel,
                reply_to_proposal_token,
                reaction_to_proposal_token,
            )
            raise BrainNotFoundError(
                message="capabilities.invoke domain failure: Not Found",
                operation="capabilities.invoke",
                details=(
                    SdkErrorDetail(
                        code="NOT_FOUND",
                        message="Not Found",
                        category="not_found",
                        metadata={"path": "notes/missing.md"},
                    ),
                ),
            )

    tools = main._build_capability_tools(
        client=_FakeClient(),  # type: ignore[arg-type]
        capabilities=(
            CapabilityDescriptor(
                capability_id="vault-rename-path",
                kind="native_op",
                version="1.0.0",
                summary="Rename one vault path.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                autonomy=0,
                requires_approval=False,
                side_effects=("writes_vault",),
                required_capabilities=(),
            ),
        ),
        turn_state=main._TurnState(actor="operator", channel="signal"),
    )

    result = tools[0].function(
        source_path="notes/missing.md",
        target_path="notes/new.md",
    )

    assert result == {
        "error": "not_found",
        "message": "capabilities.invoke domain failure: Not Found",
        "capability_id": "vault-rename-path",
        "details": [
            {
                "code": "NOT_FOUND",
                "message": "Not Found",
                "category": "not_found",
                "retryable": False,
                "metadata": {"path": "notes/missing.md"},
            }
        ],
    }


def test_build_capability_tools_returns_internal_error_payload() -> None:
    """Internal domain failures should be returned as structured tool data."""
    from actors.agent import main

    class _FakeClient:
        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
            reply_to_proposal_token: str = "",
            reaction_to_proposal_token: str = "",
        ):
            del (
                capability_id,
                input_payload,
                actor,
                channel,
                reply_to_proposal_token,
                reaction_to_proposal_token,
            )
            raise BrainInternalError(
                message="capabilities.invoke domain failure: internal fault",
                operation="capabilities.invoke",
                details=(
                    SdkErrorDetail(
                        code="INTERNAL",
                        message="internal fault",
                        category="internal",
                    ),
                ),
            )

    tools = main._build_capability_tools(
        client=_FakeClient(),  # type: ignore[arg-type]
        capabilities=(
            CapabilityDescriptor(
                capability_id="vault-rename-path",
                kind="native_op",
                version="1.0.0",
                summary="Rename one vault path.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                autonomy=0,
                requires_approval=False,
                side_effects=("writes_vault",),
                required_capabilities=(),
            ),
        ),
        turn_state=main._TurnState(actor="operator", channel="signal"),
    )

    result = tools[0].function(
        source_path="notes/old.md",
        target_path="notes/new.md",
    )

    assert result == {
        "error": "internal_error",
        "message": "capabilities.invoke domain failure: internal fault",
        "capability_id": "vault-rename-path",
        "details": [
            {
                "code": "INTERNAL",
                "message": "internal fault",
                "category": "internal",
                "retryable": False,
                "metadata": {},
            }
        ],
    }


def test_instruction_context_message_uses_reaction_approval_when_text_missing() -> None:
    """Reaction-only approvals should still produce a usable MAS context message."""
    from actors.agent import main

    assert (
        main._instruction_context_message(
            SwitchboardOperatorInstruction(
                sender_e164="+12025550100",
                message_text="",
                timestamp_ms=1,
                source_device="1",
                source="signal",
                group_id=None,
                quote_target_timestamp_ms=None,
                reaction_target_timestamp_ms=123,
                reaction_emoji="👍",
                approval_intent="approve",
            )
        )
        == "[signal reaction approval:approve emoji:👍]"
    )


def test_build_capability_tools_remembers_pending_invocation_with_expiry() -> None:
    """Approval denials should populate the short-lived pending invocation store."""
    from actors.agent import main

    class _FakeClient:
        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
            reply_to_proposal_token: str = "",
            reaction_to_proposal_token: str = "",
        ):
            del (
                capability_id,
                input_payload,
                actor,
                channel,
                reply_to_proposal_token,
                reaction_to_proposal_token,
            )
            raise BrainPolicyError(
                message=(
                    "capabilities.invoke domain failure: "
                    "policy denied capability invocation"
                ),
                operation="capabilities.invoke",
                details=(
                    SdkErrorDetail(
                        code="permission_denied",
                        message="policy denied capability invocation",
                        category="policy",
                        metadata={
                            "proposal_token": "tok-expiring",
                            "reason_codes": "approval_required",
                            "expires_at": "2099-03-13T14:15:16Z",
                        },
                    ),
                ),
            )

    turn_state = main._TurnState(actor="operator", channel="signal")
    tools = main._build_capability_tools(
        client=_FakeClient(),  # type: ignore[arg-type]
        capabilities=(
            CapabilityDescriptor(
                capability_id="vault-move-path",
                kind="native_op",
                version="1.0.0",
                summary="Move one file or directory path.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                autonomy=0,
                requires_approval=True,
                side_effects=("writes_vault",),
                required_capabilities=(),
            ),
        ),
        turn_state=turn_state,
    )

    result = tools[0].function(
        source_path="notes/old.md",
        target_path="notes/new.md",
    )

    assert result["proposal_expires_at"] == "2099-03-13T14:15:16+00:00"
    assert turn_state.pending_invocations["tok-expiring"] == main._PendingInvocation(
        proposal_token="tok-expiring",
        capability_id="vault-move-path",
        input_payload={
            "source_path": "notes/old.md",
            "target_path": "notes/new.md",
        },
        actor="operator",
        channel="signal",
        requires_approval=True,
        reason_codes=("approval_required",),
        created_at=turn_state.pending_invocations["tok-expiring"].created_at,
        expires_at=datetime(2099, 3, 13, 14, 15, 16, tzinfo=UTC),
    )


def test_build_capability_tools_forwards_matching_proposal_correlators() -> None:
    """Retries should forward correlators only when they match stored blocked work."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.reply_to_proposal_token = ""
            self.reaction_to_proposal_token = ""

        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
            reply_to_proposal_token: str = "",
            reaction_to_proposal_token: str = "",
        ):
            del capability_id, input_payload, actor, channel
            self.reply_to_proposal_token = reply_to_proposal_token
            self.reaction_to_proposal_token = reaction_to_proposal_token
            return type("InvokeResult", (), {"output": {"ok": True}})()

    client = _FakeClient()
    turn_state = main._TurnState(
        actor="operator",
        channel="signal",
        reply_to_proposal_token="tok-quote",
        reaction_to_proposal_token="tok-react",
        pending_invocations={
            "tok-quote": main._PendingInvocation(
                proposal_token="tok-quote",
                capability_id="vault-move-path",
                input_payload={
                    "source_path": "notes/old.md",
                    "target_path": "notes/new.md",
                },
                actor="operator",
                channel="signal",
                requires_approval=True,
                reason_codes=("approval_required",),
                created_at=datetime(2026, 3, 12, 12, 0, 0, tzinfo=UTC),
            ),
            "tok-react": main._PendingInvocation(
                proposal_token="tok-react",
                capability_id="vault-move-path",
                input_payload={
                    "source_path": "notes/old.md",
                    "target_path": "notes/new.md",
                },
                actor="operator",
                channel="signal",
                requires_approval=True,
                reason_codes=("approval_required",),
                created_at=datetime(2026, 3, 12, 12, 0, 1, tzinfo=UTC),
            ),
        },
    )
    tools = main._build_capability_tools(
        client=client,  # type: ignore[arg-type]
        capabilities=(
            CapabilityDescriptor(
                capability_id="vault-move-path",
                kind="native_op",
                version="1.0.0",
                summary="Move one file or directory path.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                autonomy=0,
                requires_approval=True,
                side_effects=("writes_vault",),
                required_capabilities=(),
            ),
        ),
        turn_state=turn_state,
    )

    tools[0].function(
        source_path="notes/old.md",
        target_path="notes/new.md",
    )

    assert client.reply_to_proposal_token == "tok-quote"
    assert client.reaction_to_proposal_token == "tok-react"


def test_build_capability_tools_does_not_forward_mismatched_proposal_correlators() -> (
    None
):
    """Correlators should be withheld when the retry does not match stored blocked work."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.reply_to_proposal_token = ""
            self.reaction_to_proposal_token = ""

        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
            reply_to_proposal_token: str = "",
            reaction_to_proposal_token: str = "",
        ):
            del capability_id, input_payload, actor, channel
            self.reply_to_proposal_token = reply_to_proposal_token
            self.reaction_to_proposal_token = reaction_to_proposal_token
            return type("InvokeResult", (), {"output": {"ok": True}})()

    client = _FakeClient()
    turn_state = main._TurnState(
        actor="operator",
        channel="signal",
        reply_to_proposal_token="tok-quote",
        reaction_to_proposal_token="tok-react",
        pending_invocations={
            "tok-quote": main._PendingInvocation(
                proposal_token="tok-quote",
                capability_id="vault-move-path",
                input_payload={
                    "source_path": "notes/old.md",
                    "target_path": "notes/new.md",
                },
                actor="operator",
                channel="signal",
                requires_approval=True,
                reason_codes=("approval_required",),
                created_at=datetime(2026, 3, 12, 12, 0, 0, tzinfo=UTC),
            ),
            "tok-react": main._PendingInvocation(
                proposal_token="tok-react",
                capability_id="vault-move-path",
                input_payload={
                    "source_path": "notes/old.md",
                    "target_path": "notes/new.md",
                },
                actor="operator",
                channel="signal",
                requires_approval=True,
                reason_codes=("approval_required",),
                created_at=datetime(2026, 3, 12, 12, 0, 1, tzinfo=UTC),
            ),
        },
    )
    tools = main._build_capability_tools(
        client=client,  # type: ignore[arg-type]
        capabilities=(
            CapabilityDescriptor(
                capability_id="vault-move-path",
                kind="native_op",
                version="1.0.0",
                summary="Move one file or directory path.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                autonomy=0,
                requires_approval=True,
                side_effects=("writes_vault",),
                required_capabilities=(),
            ),
        ),
        turn_state=turn_state,
    )

    tools[0].function(
        source_path="notes/other.md",
        target_path="notes/new.md",
    )

    assert client.reply_to_proposal_token == ""
    assert client.reaction_to_proposal_token == ""


def test_turn_state_prunes_expired_pending_invocations() -> None:
    """Expired pending approval records should be evicted eagerly."""
    from actors.agent import main

    now = datetime(2026, 3, 11, 12, 0, 0, tzinfo=UTC)
    turn_state = main._TurnState()
    turn_state.pending_invocations = {
        "expired": main._PendingInvocation(
            proposal_token="expired",
            capability_id="vault-move-path",
            input_payload={},
            actor="operator",
            channel="signal",
            requires_approval=True,
            reason_codes=("approval_required",),
            created_at=now - timedelta(minutes=5),
            expires_at=now - timedelta(seconds=1),
        ),
        "active": main._PendingInvocation(
            proposal_token="active",
            capability_id="vault-move-path",
            input_payload={},
            actor="operator",
            channel="signal",
            requires_approval=True,
            reason_codes=("approval_required",),
            created_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=5),
        ),
    }

    turn_state.prune_pending_invocations(now=now)

    assert set(turn_state.pending_invocations) == {"active"}


def test_turn_state_remember_pending_invocation_evicts_oldest_over_limit() -> None:
    """Pending approval records should remain bounded even without expiry data."""
    from actors.agent import main

    base = datetime(2026, 3, 11, 12, 0, 0, tzinfo=UTC)
    turn_state = main._TurnState(actor="operator", channel="signal")

    for index in range(main._MAX_PENDING_INVOCATIONS + 1):
        turn_state.remember_pending_invocation(
            proposal_token=f"tok-{index}",
            capability_id="vault-move-path",
            input_payload={"index": index},
            requires_approval=True,
            reason_codes=("approval_required",),
            now=base + timedelta(seconds=index),
        )

    assert len(turn_state.pending_invocations) == main._MAX_PENDING_INVOCATIONS
    assert "tok-0" not in turn_state.pending_invocations
    assert f"tok-{main._MAX_PENDING_INVOCATIONS}" in turn_state.pending_invocations


def test_tool_model_requests_lms_chat_with_tools() -> None:
    """Custom model should translate request history and tool schemas into SDK calls."""
    from actors.agent import main
    from pydantic_ai.messages import (
        ModelRequest,
        SystemPromptPart,
        ToolCallPart,
        UserPromptPart,
    )
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.tools import ToolDefinition

    class _FakeClient:
        def __init__(self) -> None:
            self.inference_request: InferenceRequest | None = None
            self.timeout_seconds: float | None = None

        def lms_chat_with_tools(
            self,
            *,
            inference_request: InferenceRequest,
            timeout_seconds: float | None = None,
            meta: object | None = None,
        ) -> LmsToolChatResult:
            del meta
            self.inference_request = inference_request
            self.timeout_seconds = timeout_seconds
            return LmsToolChatResult(
                provider="unit",
                model="test-model",
                finish_reason="tool_call",
                text=None,
                tool_calls=(
                    LmsChatToolCall(
                        tool_name="vault-get-file",
                        args_json='{"input_payload":{"file_path":"resume.md"}}',
                        tool_call_id="call-1",
                    ),
                ),
            )

    client = _FakeClient()
    model = main._BrainSdkToolModel(  # type: ignore[arg-type]
        client=client,
        timeout_seconds=45.0,
        session_id="session-1",
        source="agent",
        principal="operator",
        system_blocks=(InferenceSystemBlock(kind="assistant_persona", text="system"),),
    )
    response = asyncio.run(
        model.request(
            messages=[
                ModelRequest(
                    parts=[SystemPromptPart("system"), UserPromptPart("hello")]
                )
            ],
            model_settings=None,
            model_request_parameters=ModelRequestParameters(
                function_tools=[
                    ToolDefinition(
                        name="vault-get-file",
                        description="Read a file.",
                        parameters_json_schema={
                            "type": "object",
                            "properties": {
                                "input_payload": {
                                    "type": "object",
                                    "properties": {"file_path": {"type": "string"}},
                                    "required": ["file_path"],
                                }
                            },
                            "required": ["input_payload"],
                        },
                    )
                ]
            ),
        )
    )

    assert model.last_result is not None
    assert model.last_result.model == "test-model"
    assert client.timeout_seconds == 45.0
    assert client.inference_request is not None
    assert client.inference_request.meta.session_id == "session-1"
    assert client.inference_request.meta.source == "agent"
    assert client.inference_request.meta.principal == "operator"
    assert client.inference_request.meta.envelope_id is not None
    assert client.inference_request.system == InferenceSystem(
        blocks=(InferenceSystemBlock(kind="assistant_persona", text="system"),)
    )
    assert client.inference_request.current_turn == InferenceCurrentTurn(
        operator_message=InferenceOperatorMessage(
            channel="",
            sender_e164="",
            message_text="hello",
        )
    )
    assert client.inference_request.tools == (
        InferenceToolDefinition(
            name="vault-get-file",
            description="Read a file.",
            input_schema={
                "type": "object",
                "properties": {
                    "input_payload": {
                        "type": "object",
                        "properties": {"file_path": {"type": "string"}},
                        "required": ["file_path"],
                    },
                    "call_mode": {
                        "type": "string",
                        "enum": ["decide", "explore"],
                        "description": (
                            "Characterize this tool call for result handling. "
                            "Use 'decide' when you know exactly what you are looking for and the result "
                            "will directly inform your answer or next action. "
                            "Use 'explore' when you are orienting or speculatively fetching and may need "
                            "the full result to reason further."
                        ),
                    },
                    "response_detail": {
                        "type": "string",
                        "description": (
                            "State specifically what information you need from this tool result "
                            "and how you intend to use it. Used to guide result compression."
                        ),
                    },
                },
                "required": ["input_payload"],
                "additionalProperties": False,
            },
            strict_schema=None,
            execution_hints=InferenceToolExecutionHints(
                sequential=False,
                requires_approval=None,
            ),
        ),
    )
    assert isinstance(response.parts[0], ToolCallPart)
    assert response.parts[0].tool_name == "vault-get-file"


def test_tool_model_filters_unadvertised_tool_calls_from_model_response() -> None:
    """Unadvertised tool calls should be dropped so they do not poison turn history."""
    from actors.agent import main
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.tools import ToolDefinition

    class _FakeClient:
        def lms_chat_with_tools(
            self,
            *,
            inference_request: InferenceRequest,
            timeout_seconds: float | None = None,
            meta: object | None = None,
        ) -> LmsToolChatResult:
            del inference_request, timeout_seconds, meta
            return LmsToolChatResult(
                provider="unit",
                model="test-model",
                finish_reason="tool_call",
                text="Checking.",
                tool_calls=(
                    LmsChatToolCall(
                        tool_name="vault-get-file",
                        args_json='{"file_path":"a.md"}',
                        tool_call_id="call-valid",
                    ),
                    LmsChatToolCall(
                        tool_name="vault-list-directory",
                        args_json='{"directory_path":"entities"}',
                        tool_call_id="call-invalid",
                    ),
                ),
            )

    model = main._BrainSdkToolModel(  # type: ignore[arg-type]
        client=_FakeClient(),
        session_id="session-1",
        source="agent",
        principal="operator",
        system_blocks=(),
    )

    response = asyncio.run(
        model.request(
            messages=[ModelRequest(parts=[UserPromptPart("hello")])],
            model_settings=None,
            model_request_parameters=ModelRequestParameters(
                function_tools=[ToolDefinition(name="vault-get-file")]
            ),
        )
    )

    assert [part.part_kind for part in response.parts] == ["text", "tool-call"]
    assert response.parts[1].tool_name == "vault-get-file"


def test_tool_model_retries_once_when_model_returns_only_unadvertised_tool_calls() -> (
    None
):
    """Unadvertised-only tool calls should trigger one internal retry before failing."""
    from actors.agent import main
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.tools import ToolDefinition

    class _FakeClient:
        def __init__(self) -> None:
            self.calls: list[InferenceRequest] = []

        def lms_chat_with_tools(
            self,
            *,
            inference_request: InferenceRequest,
            timeout_seconds: float | None = None,
            meta: object | None = None,
        ) -> LmsToolChatResult:
            del timeout_seconds, meta
            self.calls.append(inference_request)
            if len(self.calls) == 1:
                return LmsToolChatResult(
                    provider="unit",
                    model="test-model",
                    finish_reason="tool_call",
                    text=None,
                    tool_calls=(
                        LmsChatToolCall(
                            tool_name="vault-list-directory",
                            args_json='{"directory_path":"entities"}',
                            tool_call_id="call-invalid",
                        ),
                    ),
                )
            return LmsToolChatResult(
                provider="unit",
                model="test-model",
                finish_reason="tool_call",
                text=None,
                tool_calls=(
                    LmsChatToolCall(
                        tool_name="vault-get-file",
                        args_json='{"file_path":"heidi.md"}',
                        tool_call_id="call-valid",
                    ),
                ),
            )

    client = _FakeClient()
    model = main._BrainSdkToolModel(  # type: ignore[arg-type]
        client=client,
        session_id="session-1",
        source="agent",
        principal="operator",
        system_blocks=(),
    )

    response = asyncio.run(
        model.request(
            messages=[ModelRequest(parts=[UserPromptPart("hello")])],
            model_settings=None,
            model_request_parameters=ModelRequestParameters(
                function_tools=[ToolDefinition(name="vault-get-file")]
            ),
        )
    )

    assert len(client.calls) == 2
    assert (
        client.calls[1].system.blocks[-1].text
        == main._INVALID_TOOL_CALL_RETRY_INSTRUCTION
    )
    assert response.parts[0].tool_name == "vault-get-file"
    assert response.parts[0].tool_call_id == "call-valid"


def test_process_instruction_assembles_context_and_records_response() -> None:
    """One processed instruction should assemble MAS context and record the reply."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.inbound: list[
                tuple[str, str, SwitchboardOperatorInstruction | None]
            ] = []
            self.snapshots: list[str] = []
            self.recorded: list[tuple[str, str, str, str, int, str]] = []
            self.deliveries: list[tuple[str, str, bool]] = []
            self.invoked: list[tuple[str, dict[str, object], str, str]] = []

        def memory_record_inbound_turn(
            self,
            *,
            session_id: str,
            message: str,
            instruction: SwitchboardOperatorInstruction | None = None,
        ):
            self.inbound.append((session_id, message, instruction))
            return type("TurnRecord", (), {"id": "turn-inbound"})()

        def memory_assemble_snapshot(self, *, session_id: str) -> MemoryContextBlock:
            self.snapshots.append(session_id)
            return MemoryContextBlock(
                current_focus="current focus",
                recent_conversation_summary="prior summary",
                recent_turns=(
                    MemoryDialogueTurn(
                        role="assistant",
                        content="prior turn",
                        is_summary=False,
                    ),
                ),
                reference_snippets=("snippet",),
            )

        def memory_record_outbound_candidate(
            self,
            *,
            session_id: str,
            content: str,
            model: str,
            provider: str,
            token_count: int,
            reasoning_level: str,
        ):
            self.recorded.append(
                (session_id, content, model, provider, token_count, reasoning_level)
            )
            return type("TurnRecord", (), {"id": "turn-outbound"})()

        def memory_record_outbound_delivery(
            self,
            *,
            session_id: str,
            turn_id: str,
            delivered: bool,
        ) -> bool:
            self.deliveries.append((session_id, turn_id, delivered))
            return delivered

        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
        ):
            self.invoked.append((capability_id, input_payload, actor, channel))
            return type("InvokeResult", (), {"output": {"decision": "sent"}})()

    @dataclass
    class _FakeRunResult:
        output: str

    class _FakeAgent:
        def __init__(self, runtime) -> None:
            self._runtime = runtime

        async def run(self, _prompt: str) -> _FakeRunResult:
            self._runtime.model.last_result = LmsToolChatResult(
                provider="unit",
                model="test-model",
                finish_reason="stop",
                text="assistant reply",
                tool_calls=(),
            )
            return _FakeRunResult(output="assistant reply")

    client = _FakeClient()
    runtime = main._AgentRuntime(
        client=client,  # type: ignore[arg-type]
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        turn_state=main._TurnState(),
        model=main._BrainSdkToolModel.__new__(main._BrainSdkToolModel),
        agent=None,  # type: ignore[arg-type]
        lms_request_timeout_seconds=45.0,
    )
    runtime.model.last_result = None
    runtime.agent = _FakeAgent(runtime)  # type: ignore[assignment]

    response = asyncio.run(
        main._process_instruction(
            runtime=runtime,
            instruction=SwitchboardOperatorInstruction(
                sender_e164="+12025550100",
                message_text="hello",
                timestamp_ms=1,
                source_device="1",
                source="signal",
                group_id=None,
                quote_target_timestamp_ms=None,
                reaction_target_timestamp_ms=None,
                reaction_emoji=None,
                approval_intent=None,
            ),
        )
    )

    assert response == "assistant reply"
    assert client.inbound == [
        (
            "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "hello",
            SwitchboardOperatorInstruction(
                sender_e164="+12025550100",
                message_text="hello",
                timestamp_ms=1,
                source_device="1",
                source="signal",
                group_id=None,
                quote_target_timestamp_ms=None,
                reaction_target_timestamp_ms=None,
                reaction_emoji=None,
                approval_intent=None,
                reply_to_proposal_token=None,
                reaction_to_proposal_token=None,
            ),
        )
    ]
    assert client.snapshots == ["01ARZ3NDEKTSV4RRFFQ69G5FAV"]
    assert client.recorded == []
    assert client.deliveries == []
    assert client.invoked == [
        (
            "attention-notify",
            {
                "actor": "operator",
                "channel": "signal",
                "message": "assistant reply",
                "conversational_memory": {
                    "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    "model": "test-model",
                    "provider": "unit",
                    "token_count": main._estimate_token_count("assistant reply"),
                    "reasoning_level": "standard",
                },
            },
            "operator",
            "signal",
        )
    ]


def test_process_instruction_handles_lms_throttle_gracefully(monkeypatch) -> None:
    """Retryable LMS rate limiting should produce a fallback operator response."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.inbound: list[
                tuple[str, str, SwitchboardOperatorInstruction | None]
            ] = []
            self.snapshots: list[str] = []
            self.recorded: list[tuple[str, str, str, str, int, str]] = []
            self.deliveries: list[tuple[str, str, bool]] = []
            self.invoked: list[tuple[str, dict[str, object], str, str]] = []

        def memory_record_inbound_turn(
            self,
            *,
            session_id: str,
            message: str,
            instruction: SwitchboardOperatorInstruction | None = None,
        ):
            self.inbound.append((session_id, message, instruction))
            return type("TurnRecord", (), {"id": "turn-inbound"})()

        def memory_assemble_snapshot(self, *, session_id: str) -> MemoryContextBlock:
            self.snapshots.append(session_id)
            return MemoryContextBlock(
                current_focus="current focus",
                recent_conversation_summary="prior summary",
                recent_turns=(
                    MemoryDialogueTurn(
                        role="assistant",
                        content="prior turn",
                        is_summary=False,
                    ),
                ),
                reference_snippets=(),
            )

        def memory_record_outbound_candidate(
            self,
            *,
            session_id: str,
            content: str,
            model: str,
            provider: str,
            token_count: int,
            reasoning_level: str,
        ):
            self.recorded.append(
                (session_id, content, model, provider, token_count, reasoning_level)
            )
            return type("TurnRecord", (), {"id": "turn-outbound"})()

        def memory_record_outbound_delivery(
            self,
            *,
            session_id: str,
            turn_id: str,
            delivered: bool,
        ) -> bool:
            self.deliveries.append((session_id, turn_id, delivered))
            return delivered

        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
        ):
            self.invoked.append((capability_id, input_payload, actor, channel))
            return type("InvokeResult", (), {"output": {"decision": "sent"}})()

    class _FakeAgent:
        async def run(self, _prompt: str):
            raise BrainDependencyError(
                message=(
                    "lms.chat_with_tools domain failure: provider rate limit exceeded"
                ),
                operation="lms.chat_with_tools",
                details=(
                    SdkErrorDetail(
                        code="dependency_unavailable",
                        message="provider rate limit exceeded",
                        category="dependency",
                        retryable=True,
                    ),
                ),
            )

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(main.asyncio, "sleep", _no_sleep)
    client = _FakeClient()
    runtime = main._AgentRuntime(
        client=client,  # type: ignore[arg-type]
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        turn_state=main._TurnState(),
        model=main._BrainSdkToolModel.__new__(main._BrainSdkToolModel),
        agent=_FakeAgent(),  # type: ignore[arg-type]
        lms_request_timeout_seconds=45.0,
    )
    runtime.model.last_result = None

    response = asyncio.run(
        main._process_instruction(
            runtime=runtime,
            instruction=SwitchboardOperatorInstruction(
                sender_e164="+12025550100",
                message_text="hello",
                timestamp_ms=1,
                source_device="1",
                source="signal",
                group_id=None,
                quote_target_timestamp_ms=None,
                reaction_target_timestamp_ms=None,
                reaction_emoji=None,
                approval_intent=None,
            ),
        )
    )

    assert response == main._LMS_THROTTLE_RESPONSE
    assert client.recorded == []
    assert client.invoked == [
        (
            "attention-notify",
            {
                "actor": "operator",
                "channel": "signal",
                "message": main._LMS_THROTTLE_RESPONSE,
                "conversational_memory": {
                    "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    "model": "brain-sdk-lms",
                    "provider": "brain-sdk",
                    "token_count": main._estimate_token_count(
                        main._LMS_THROTTLE_RESPONSE
                    ),
                    "reasoning_level": "standard",
                },
            },
            "operator",
            "signal",
        ),
    ]


def test_process_instruction_handles_lms_timeout_gracefully(monkeypatch) -> None:
    """Retryable LMS timeout should produce a fallback operator response."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.recorded: list[tuple[str, str, str, str, int, str]] = []
            self.invoked: list[tuple[str, dict[str, object], str, str]] = []

        def memory_record_inbound_turn(
            self,
            *,
            session_id: str,
            message: str,
            instruction: SwitchboardOperatorInstruction | None = None,
        ):
            del message, instruction
            return type("TurnRecord", (), {"id": f"{session_id}-inbound"})()

        def memory_assemble_snapshot(self, *, session_id: str) -> MemoryContextBlock:
            del session_id
            return MemoryContextBlock(
                current_focus="current focus",
                recent_conversation_summary="prior summary",
                recent_turns=(),
                reference_snippets=(),
            )

        def memory_record_outbound_candidate(
            self,
            *,
            session_id: str,
            content: str,
            model: str,
            provider: str,
            token_count: int,
            reasoning_level: str,
        ):
            self.recorded.append(
                (session_id, content, model, provider, token_count, reasoning_level)
            )
            return type("TurnRecord", (), {"id": "turn-outbound"})()

        def memory_record_outbound_delivery(
            self,
            *,
            session_id: str,
            turn_id: str,
            delivered: bool,
        ) -> bool:
            del session_id, turn_id
            return delivered

        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
        ):
            self.invoked.append((capability_id, input_payload, actor, channel))
            return type("InvokeResult", (), {"output": {"decision": "sent"}})()

    class _FakeAgent:
        async def run(self, _prompt: str):
            raise BrainDependencyError(
                message="lms.chat_with_tools domain failure: provider timed out",
                operation="lms.chat_with_tools",
                details=(
                    SdkErrorDetail(
                        code="dependency_unavailable",
                        message="provider timed out",
                        category="dependency",
                        retryable=True,
                    ),
                ),
            )

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(main.asyncio, "sleep", _no_sleep)
    client = _FakeClient()
    runtime = main._AgentRuntime(
        client=client,  # type: ignore[arg-type]
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        turn_state=main._TurnState(),
        model=main._BrainSdkToolModel.__new__(main._BrainSdkToolModel),
        agent=_FakeAgent(),  # type: ignore[arg-type]
        lms_request_timeout_seconds=45.0,
    )
    runtime.model.last_result = None

    response = asyncio.run(
        main._process_instruction(
            runtime=runtime,
            instruction=SwitchboardOperatorInstruction(
                sender_e164="+12025550100",
                message_text="hello",
                timestamp_ms=1,
                source_device="1",
                source="signal",
                group_id=None,
                quote_target_timestamp_ms=None,
                reaction_target_timestamp_ms=None,
                reaction_emoji=None,
                approval_intent=None,
            ),
        )
    )

    assert response == main._LMS_TIMEOUT_RESPONSE
    assert client.recorded == []
    assert client.invoked == [
        (
            "attention-notify",
            {
                "actor": "operator",
                "channel": "signal",
                "message": main._LMS_TIMEOUT_RESPONSE,
                "conversational_memory": {
                    "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    "model": "brain-sdk-lms",
                    "provider": "brain-sdk",
                    "token_count": main._estimate_token_count(
                        main._LMS_TIMEOUT_RESPONSE
                    ),
                    "reasoning_level": "standard",
                },
            },
            "operator",
            "signal",
        ),
    ]


def test_process_instruction_handles_lms_internal_error_gracefully() -> None:
    """Non-timeout LMS domain errors should produce the generic fallback response."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.recorded: list[tuple[str, str, str, str, int, str]] = []
            self.invoked: list[tuple[str, dict[str, object], str, str]] = []

        def memory_record_inbound_turn(
            self,
            *,
            session_id: str,
            message: str,
            instruction: SwitchboardOperatorInstruction | None = None,
        ):
            del message, instruction
            return type("TurnRecord", (), {"id": f"{session_id}-inbound"})()

        def memory_assemble_snapshot(self, *, session_id: str) -> MemoryContextBlock:
            del session_id
            return MemoryContextBlock(
                current_focus="current focus",
                recent_conversation_summary="prior summary",
                recent_turns=(),
                reference_snippets=(),
            )

        def memory_record_outbound_candidate(
            self,
            *,
            session_id: str,
            content: str,
            model: str,
            provider: str,
            token_count: int,
            reasoning_level: str,
        ):
            self.recorded.append(
                (session_id, content, model, provider, token_count, reasoning_level)
            )
            return type("TurnRecord", (), {"id": "turn-outbound"})()

        def memory_record_outbound_delivery(
            self,
            *,
            session_id: str,
            turn_id: str,
            delivered: bool,
        ) -> bool:
            del session_id, turn_id
            return delivered

        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
        ):
            self.invoked.append((capability_id, input_payload, actor, channel))
            return type("InvokeResult", (), {"output": {"decision": "sent"}})()

    class _FakeAgent:
        async def run(self, _prompt: str):
            raise BrainInternalError(
                message="lms.chat_with_tools domain failure: invalid request transcript",
                operation="lms.chat_with_tools",
                details=(
                    SdkErrorDetail(
                        code="internal_error",
                        message="invalid request transcript",
                        category="internal",
                        retryable=False,
                    ),
                ),
            )

    client = _FakeClient()
    runtime = main._AgentRuntime(
        client=client,  # type: ignore[arg-type]
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        turn_state=main._TurnState(),
        model=main._BrainSdkToolModel.__new__(main._BrainSdkToolModel),
        agent=_FakeAgent(),  # type: ignore[arg-type]
        lms_request_timeout_seconds=45.0,
    )
    runtime.model.last_result = None

    response = asyncio.run(
        main._process_instruction(
            runtime=runtime,
            instruction=SwitchboardOperatorInstruction(
                sender_e164="+12025550100",
                message_text="hello",
                timestamp_ms=1,
                source_device="1",
                source="signal",
                group_id=None,
                quote_target_timestamp_ms=None,
                reaction_target_timestamp_ms=None,
                reaction_emoji=None,
                approval_intent=None,
            ),
        )
    )

    assert response == main._LMS_GENERIC_ERROR_RESPONSE
    assert client.recorded == []
    assert client.invoked == [
        (
            "attention-notify",
            {
                "actor": "operator",
                "channel": "signal",
                "message": main._LMS_GENERIC_ERROR_RESPONSE,
                "conversational_memory": {
                    "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    "model": "brain-sdk-lms",
                    "provider": "brain-sdk",
                    "token_count": main._estimate_token_count(
                        main._LMS_GENERIC_ERROR_RESPONSE
                    ),
                    "reasoning_level": "standard",
                },
            },
            "operator",
            "signal",
        )
    ]


def test_process_instruction_handles_retryable_internal_error_with_generic_fallback() -> (
    None
):
    """Retryable internal errors from outside model.request still fall back cleanly."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.recorded: list[tuple[str, str, str, str, int, str]] = []
            self.invoked: list[tuple[str, dict[str, object], str, str]] = []

        def memory_record_inbound_turn(
            self,
            *,
            session_id: str,
            message: str,
            instruction: SwitchboardOperatorInstruction | None = None,
        ):
            del message, instruction
            return type("TurnRecord", (), {"id": f"{session_id}-inbound"})()

        def memory_assemble_snapshot(self, *, session_id: str) -> MemoryContextBlock:
            del session_id
            return MemoryContextBlock(
                current_focus="current focus",
                recent_conversation_summary="prior summary",
                recent_turns=(),
                reference_snippets=(),
            )

        def memory_record_outbound_candidate(
            self,
            *,
            session_id: str,
            content: str,
            model: str,
            provider: str,
            token_count: int,
            reasoning_level: str,
        ):
            self.recorded.append(
                (session_id, content, model, provider, token_count, reasoning_level)
            )
            return type("TurnRecord", (), {"id": "turn-outbound"})()

        def memory_record_outbound_delivery(
            self,
            *,
            session_id: str,
            turn_id: str,
            delivered: bool,
        ) -> bool:
            del session_id, turn_id
            return delivered

        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
        ):
            self.invoked.append((capability_id, input_payload, actor, channel))
            return type("InvokeResult", (), {"output": {"decision": "sent"}})()

    class _FakeAgent:
        async def run(self, _prompt: str):
            raise BrainInternalError(
                message=(
                    "lms.chat_with_tools domain failure: model returned "
                    "unadvertised tool call(s): vault-list-directory"
                ),
                operation="lms.chat_with_tools",
                details=(
                    SdkErrorDetail(
                        code="INVALID_TOOL_CALL",
                        message="model returned unadvertised tool call",
                        category="internal",
                        retryable=True,
                    ),
                ),
            )

    client = _FakeClient()
    runtime = main._AgentRuntime(
        client=client,  # type: ignore[arg-type]
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        turn_state=main._TurnState(),
        model=main._BrainSdkToolModel.__new__(main._BrainSdkToolModel),
        agent=None,  # type: ignore[arg-type]
        lms_request_timeout_seconds=45.0,
    )
    runtime.model.last_result = None
    runtime.agent = _FakeAgent()  # type: ignore[assignment]

    response = asyncio.run(
        main._process_instruction(
            runtime=runtime,
            instruction=SwitchboardOperatorInstruction(
                sender_e164="+12025550100",
                message_text="hello",
                timestamp_ms=1,
                source_device="1",
                source="signal",
                group_id=None,
                quote_target_timestamp_ms=None,
                reaction_target_timestamp_ms=None,
                reaction_emoji=None,
                approval_intent=None,
            ),
        )
    )

    assert response == main._LMS_GENERIC_ERROR_RESPONSE
    assert client.recorded == []
    assert client.invoked == [
        (
            "attention-notify",
            {
                "actor": "operator",
                "channel": "signal",
                "message": main._LMS_GENERIC_ERROR_RESPONSE,
                "conversational_memory": {
                    "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    "model": "brain-sdk-lms",
                    "provider": "brain-sdk",
                    "token_count": main._estimate_token_count(
                        main._LMS_GENERIC_ERROR_RESPONSE
                    ),
                    "reasoning_level": "standard",
                },
            },
            "operator",
            "signal",
        )
    ]


def test_process_instruction_handles_lms_transport_5xx_gracefully(monkeypatch) -> None:
    """LMS transport failures should produce the generic fallback response."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.recorded: list[tuple[str, str, str, str, int, str]] = []
            self.invoked: list[tuple[str, dict[str, object], str, str]] = []

        def memory_record_inbound_turn(
            self,
            *,
            session_id: str,
            message: str,
            instruction: SwitchboardOperatorInstruction | None = None,
        ):
            del message, instruction
            return type("TurnRecord", (), {"id": f"{session_id}-inbound"})()

        def memory_assemble_snapshot(self, *, session_id: str) -> MemoryContextBlock:
            del session_id
            return MemoryContextBlock(
                current_focus="current focus",
                recent_conversation_summary="prior summary",
                recent_turns=(),
                reference_snippets=(),
            )

        def memory_record_outbound_candidate(
            self,
            *,
            session_id: str,
            content: str,
            model: str,
            provider: str,
            token_count: int,
            reasoning_level: str,
        ):
            self.recorded.append(
                (session_id, content, model, provider, token_count, reasoning_level)
            )
            return type("TurnRecord", (), {"id": "turn-outbound"})()

        def memory_record_outbound_delivery(
            self,
            *,
            session_id: str,
            turn_id: str,
            delivered: bool,
        ) -> bool:
            del session_id, turn_id
            return delivered

        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
        ):
            self.invoked.append((capability_id, input_payload, actor, channel))
            return type("InvokeResult", (), {"output": {"decision": "sent"}})()

    class _FakeAgent:
        async def run(self, _prompt: str):
            raise BrainTransportError(
                message="lms.chat_with_tools transport failure (HTTP 502): bad gateway",
                operation="lms.chat_with_tools",
                status_code=502,
                retryable=False,
            )

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(main.asyncio, "sleep", _no_sleep)
    client = _FakeClient()
    runtime = main._AgentRuntime(
        client=client,  # type: ignore[arg-type]
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        turn_state=main._TurnState(),
        model=main._BrainSdkToolModel.__new__(main._BrainSdkToolModel),
        agent=_FakeAgent(),  # type: ignore[arg-type]
        lms_request_timeout_seconds=45.0,
    )
    runtime.model.last_result = None

    response = asyncio.run(
        main._process_instruction(
            runtime=runtime,
            instruction=SwitchboardOperatorInstruction(
                sender_e164="+12025550100",
                message_text="hello",
                timestamp_ms=1,
                source_device="1",
                source="signal",
                group_id=None,
                quote_target_timestamp_ms=None,
                reaction_target_timestamp_ms=None,
                reaction_emoji=None,
                approval_intent=None,
            ),
        )
    )

    assert response == main._LMS_GENERIC_ERROR_RESPONSE
    assert client.recorded == []
    assert client.invoked == [
        (
            "attention-notify",
            {
                "actor": "operator",
                "channel": "signal",
                "message": main._LMS_GENERIC_ERROR_RESPONSE,
                "conversational_memory": {
                    "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    "model": "brain-sdk-lms",
                    "provider": "brain-sdk",
                    "token_count": main._estimate_token_count(
                        main._LMS_GENERIC_ERROR_RESPONSE
                    ),
                    "reasoning_level": "standard",
                },
            },
            "operator",
            "signal",
        ),
    ]


def test_derive_lms_request_timeout_seconds_uses_largest_chat_provider_budget() -> None:
    """Derived LMS timeout should reflect retry budget plus margin across profiles."""
    from actors.agent import main
    from packages.brain_shared.config import (
        CoreRuntimeSettings,
        CoreSettings,
        ResourcesSettings,
    )

    runtime_settings = CoreRuntimeSettings(
        core=CoreSettings.model_validate(
            {
                "service": {
                    "language_model": {
                        "quick": {"provider": "anthropic", "model": "haiku"},
                        "standard": {"provider": "anthropic", "model": "sonnet"},
                        "deep": {"provider": "openai", "model": "gpt-5"},
                    }
                }
            }
        ),
        resources=ResourcesSettings.model_validate(
            {
                "adapter": {
                    "llm": {
                        "timeout_seconds": 20.0,
                        "timeout_retry_attempts": 2,
                        "timeout_retry_initial_delay_seconds": 0.5,
                        "timeout_retry_max_delay_seconds": 2.0,
                        "timeout_retry_backoff_multiplier": 2.0,
                        "providers": {
                            "anthropic": {"timeout_seconds": 30.0},
                            "openai": {"timeout_seconds": 15.0},
                        },
                    }
                }
            }
        ),
    )

    assert main._derive_lms_request_timeout_seconds(runtime_settings) == 93.5


def test_create_runtime_reuses_existing_session_and_registers_tools() -> None:
    """Runtime creation should reuse-or-create by default and register tools."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.created = 0
            self.reused = 0
            self.described = 0
            self.always_on = 0

        def memory_create_session(self) -> MemorySessionRef:
            self.created += 1
            return MemorySessionRef(session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV")

        def memory_get_latest_or_create_session(self) -> MemorySessionRef:
            self.reused += 1
            return MemorySessionRef(session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV")

        def describe_capabilities(self) -> tuple[CapabilityDescriptor, ...]:
            self.described += 1
            return (
                CapabilityDescriptor(
                    capability_id="demo-tool",
                    kind="native_op",
                    version="1.0.0",
                    summary="Do the thing.",
                    input_schema={"value": "string"},
                    output_schema={"ok": "boolean"},
                    autonomy=0,
                    requires_approval=False,
                    side_effects=(),
                    required_capabilities=(),
                ),
            )

        def list_always_on_capabilities(self) -> tuple[CapabilityDescriptor, ...]:
            self.always_on += 1
            return ()

    client = _FakeClient()
    runtime = main._create_runtime(
        client=client,  # type: ignore[arg-type]
        settings=_actor_settings_stub(),
        core_settings=_core_settings_stub(),
    )

    assert client.reused == 1
    assert client.created == 0
    assert runtime.session_id == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert isinstance(runtime.model, main._BrainSdkToolModel)
    assert len(runtime.agent._function_toolset.tools) == 3
    assert "attention-notify" not in runtime.turn_state.active_tool_names


def test_create_runtime_uses_new_session_mode_when_configured() -> None:
    """Runtime creation should always create a new session in new mode."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.created = 0
            self.reused = 0

        def memory_create_session(self) -> MemorySessionRef:
            self.created += 1
            return MemorySessionRef(session_id="new-session")

        def memory_get_latest_or_create_session(self) -> MemorySessionRef:
            self.reused += 1
            return MemorySessionRef(session_id="existing-session")

        def describe_capabilities(self) -> tuple[CapabilityDescriptor, ...]:
            return ()

        def list_always_on_capabilities(self) -> tuple[CapabilityDescriptor, ...]:
            return ()

    settings = _actor_settings_stub()
    settings.agent.session_start_mode = "new"
    client = _FakeClient()

    runtime = main._create_runtime(
        client=client,  # type: ignore[arg-type],
        settings=settings,
        core_settings=_core_settings_stub(),
    )

    assert client.created == 1
    assert client.reused == 0
    assert runtime.session_id == "new-session"


def test_create_runtime_falls_back_to_new_session_when_existing_lookup_fails() -> None:
    """Runtime creation should create a new session when existing-mode lookup fails."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.created = 0
            self.reused = 0

        def memory_create_session(self) -> MemorySessionRef:
            self.created += 1
            return MemorySessionRef(session_id="new-session")

        def memory_get_latest_or_create_session(self) -> MemorySessionRef:
            self.reused += 1
            raise RuntimeError("lookup failed")

        def describe_capabilities(self) -> tuple[CapabilityDescriptor, ...]:
            return ()

        def list_always_on_capabilities(self) -> tuple[CapabilityDescriptor, ...]:
            return ()

    client = _FakeClient()

    runtime = main._create_runtime(
        client=client,  # type: ignore[arg-type],
        settings=_actor_settings_stub(),
        core_settings=_core_settings_stub(),
    )

    assert client.reused == 1
    assert client.created == 1
    assert runtime.session_id == "new-session"


def test_create_runtime_aborts_when_new_session_creation_fails() -> None:
    """Runtime creation should fail when the create-session path fails."""
    from actors.agent import main

    class _FakeClient:
        def memory_create_session(self) -> MemorySessionRef:
            raise RuntimeError("create failed")

        def memory_get_latest_or_create_session(self) -> MemorySessionRef:
            raise RuntimeError("lookup failed")

        def describe_capabilities(self) -> tuple[CapabilityDescriptor, ...]:
            return ()

        def list_always_on_capabilities(self) -> tuple[CapabilityDescriptor, ...]:
            return ()

    try:
        main._create_runtime(
            client=_FakeClient(),  # type: ignore[arg-type]
            settings=_actor_settings_stub(),
            core_settings=_core_settings_stub(),
        )
        assert False, "expected create-session failure to abort runtime creation"
    except RuntimeError as exc:
        assert str(exc) == "create failed"


def test_runtime_discovery_tools_do_not_activate_capabilities_for_prepare_tools() -> (
    None
):
    """Discovery should not mutate the callable tool set within the current turn."""
    from actors.agent import main
    from pydantic_ai.tools import ToolDefinition

    class _FakeClient:
        def search_capabilities(
            self, *, query: str, limit: int | None = None
        ) -> tuple[CapabilitySearchHit, ...]:
            assert query == "find vault read tools"
            assert limit == 5
            return (
                CapabilitySearchHit(
                    capability_id="vault-get-file",
                    required_params=("file_path",),
                    summary="Read one markdown file by path.",
                ),
            )

        def describe_capability(self, *, capability_id: str) -> CapabilityDescriptor:
            assert capability_id == "vault-get-file"
            return CapabilityDescriptor(
                capability_id="vault-get-file",
                kind="native_op",
                version="1.0.0",
                summary="Read one markdown file by path.",
                input_schema={
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                    "additionalProperties": False,
                },
                output_schema={"type": "object"},
                autonomy=0,
                requires_approval=False,
                side_effects=(),
                required_capabilities=(),
            )

    turn_state = main._TurnState(
        always_on_capability_ids=frozenset({"vault-search-files"})
    )
    turn_state.reset_active_tools()
    runtime_tools = main._build_runtime_tools(
        client=_FakeClient(),  # type: ignore[arg-type]
        turn_state=turn_state,
    )

    discover_result = runtime_tools[0].function(
        query="find vault read tools",
        limit=5,
        call_mode="explore",
        response_detail="Find relevant read tools before selecting one.",
    )
    assert discover_result == [
        {
            "tool_id": "vault-get-file",
            "required_params": ["file_path"],
            "summary": "Read one markdown file by path.",
        }
    ]
    assert "vault-get-file" not in turn_state.active_tool_names

    prepare_tools = main._build_prepare_tools(turn_state=turn_state)
    prepared = asyncio.run(
        prepare_tools(
            None,
            [
                ToolDefinition(name="vault-search-files"),
                ToolDefinition(name="vault-get-file"),
                ToolDefinition(name="attention-notify"),
                ToolDefinition(name=main._SEARCH_TOOLS_TOOL_NAME),
            ],
        )
    )
    assert [item.name for item in prepared] == [
        "vault-search-files",
        main._SEARCH_TOOLS_TOOL_NAME,
    ]


def test_allow_parallel_tool_calls_is_disabled_after_search_tool_result() -> None:
    """Discovery results disable parallelism because the next hop may expose new tools."""
    from actors.agent import main
    from pydantic_ai.messages import ModelRequest, ToolReturnPart

    assert (
        main._allow_parallel_tool_calls(
            messages=[
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name=main._SEARCH_TOOLS_TOOL_NAME,
                            content="[]",
                            tool_call_id="call-1",
                        )
                    ]
                )
            ]
        )
        is False
    )


def test_allow_parallel_tool_calls_is_disabled_after_get_tool_info_result() -> None:
    """Tool-info results disable parallelism because they can change next-hop callability."""
    from actors.agent import main
    from pydantic_ai.messages import ModelRequest, ToolReturnPart

    assert (
        main._allow_parallel_tool_calls(
            messages=[
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name=main._GET_TOOL_INFO_TOOL_NAME,
                            content="{}",
                            tool_call_id="call-1",
                        )
                    ]
                )
            ]
        )
        is False
    )


def test_allow_parallel_tool_calls_remains_enabled_after_non_discovery_results() -> (
    None
):
    """Ordinary tool results keep parallelism enabled because they do not mutate tool exposure."""
    from actors.agent import main
    from pydantic_ai.messages import ModelRequest, ToolReturnPart

    assert (
        main._allow_parallel_tool_calls(
            messages=[
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="vault-get-file",
                            content="{}",
                            tool_call_id="call-1",
                        )
                    ]
                )
            ]
        )
        is True
    )


def test_allow_parallel_tool_calls_defaults_enabled_before_any_tool_results() -> None:
    """The first LMS hop allows parallelism because no prior tool result can change availability."""
    from actors.agent import main

    assert main._allow_parallel_tool_calls(messages=[]) is True


def test_runtime_discovery_tools_filter_denied_capabilities() -> None:
    """Discovery and describe should not activate deny-listed capabilities."""
    from actors.agent import main

    class _FakeClient:
        def search_capabilities(
            self, *, query: str, limit: int | None = None
        ) -> tuple[CapabilitySearchHit, ...]:
            assert query == "send signal message"
            assert limit == 5
            return (
                CapabilitySearchHit(
                    capability_id="attention-notify",
                    required_params=("message",),
                    summary="Route one outbound notification.",
                ),
                CapabilitySearchHit(
                    capability_id="vault-get-file",
                    required_params=("file_path",),
                    summary="Read one markdown file by path.",
                ),
            )

        def describe_capability(self, *, capability_id: str) -> CapabilityDescriptor:
            assert capability_id == "vault-get-file"
            return CapabilityDescriptor(
                capability_id="vault-get-file",
                kind="native_op",
                version="1.0.0",
                summary="Read one markdown file by path.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                autonomy=0,
                requires_approval=False,
                side_effects=(),
                required_capabilities=(),
            )

    turn_state = main._TurnState(
        always_on_capability_ids=frozenset({"vault-search-files"}),
        denied_capability_ids=frozenset({"attention-notify"}),
    )
    turn_state.reset_active_tools()
    runtime_tools = main._build_runtime_tools(
        client=_FakeClient(),  # type: ignore[arg-type]
        turn_state=turn_state,
    )

    discover_result = runtime_tools[0].function(
        query="send signal message",
        limit=5,
        call_mode="explore",
        response_detail="Check whether a messaging capability is available.",
    )
    assert discover_result == [
        {
            "tool_id": "vault-get-file",
            "required_params": ["file_path"],
            "summary": "Read one markdown file by path.",
        }
    ]
    assert "attention-notify" not in turn_state.active_tool_names

    describe_result = runtime_tools[1].function(
        tool_id="attention-notify",
        call_mode="decide",
        response_detail="Inspect whether this capability can be used right now.",
    )
    assert describe_result == {
        "tool_id": "attention-notify",
        "available": False,
        "reason": "tool is not available to this agent",
    }
    assert "attention-notify" not in turn_state.active_tool_names
