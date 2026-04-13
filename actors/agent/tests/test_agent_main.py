"""Behavior tests for the Brain Agent process entrypoint."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from packages.brain_sdk import (
    BrainDependencyError,
    BrainInternalError,
    BrainNotFoundError,
    BrainPolicyError,
    CapabilityDescriptor,
    CapabilitySearchHit,
    LmsChatMessage,
    LmsChatToolCall,
    LmsChatToolDefinition,
    LmsToolChatResult,
    MemoryContextBlock,
    MemoryDialogueTurn,
    MemoryProfileContext,
    MemorySessionRef,
    SwitchboardOperatorInstruction,
)
from packages.brain_sdk.errors import SdkErrorDetail


def _actor_settings_stub(**agent_overrides):
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
        agent=SimpleNamespace(
            capability_discovery_deny_list=(),
            tool_return_compress_threshold=4000,
            tool_return_max_chars=8000,
            tool_loop_tier2_hop_threshold=3,
            **agent_overrides,
        ),
    )


def _core_settings_stub(personality: str = "default"):
    return SimpleNamespace(profile=SimpleNamespace(personality=personality))


def test_resolve_config_path_uses_env_override(monkeypatch) -> None:
    """Config-path helper should return a Path only when the env var is set."""
    from actors.agent import main

    monkeypatch.setenv("BRAIN_ACTORS_CONFIG_FILE", "/tmp/actors.yaml")

    assert main._resolve_config_path() == Path("/tmp/actors.yaml")


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
    from packages.brain_sdk.personality import _TEMPLATE_PATH, render_system_prompt

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "{{identity}}" in template
    assert "{identity}" not in template.replace("{{identity}}", "")

    prompt = render_system_prompt("default")

    assert prompt != ""
    assert "tool" in prompt.lower()
    assert "Brain" in prompt


def test_render_system_prompt_template_rejects_unresolved_placeholders() -> None:
    """System prompt template renderer should reject unresolved double-brace vars."""
    from packages.brain_sdk.personality import _render_template

    try:
        _render_template("Hello {{identity}} {{missing}}", identity="Brain")
        assert False, "expected unresolved placeholder validation"
    except ValueError as exc:
        assert "missing" in str(exc)


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

    assert prompt == main._COMPRESS_SYSTEM_PROMPT
    assert "tool result compressor" in prompt.lower()


def test_load_prompt_file_reads_compressor_user_template_from_disk() -> None:
    """Prompt-file helper should load the colocated compressor user template."""
    from actors.agent import main

    prompt = main._load_prompt_file(main._COMPRESS_USER_PROMPT_TEMPLATE_PATH)

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


def test_to_sdk_messages_translates_tool_loop_history() -> None:
    """Message translation should preserve assistant tool calls and tool returns."""
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

    result = main._to_sdk_messages(messages)

    assert result == [
        LmsChatMessage(role="system", content="system"),
        LmsChatMessage(role="user", content="hello"),
        LmsChatMessage(
            role="assistant",
            content="checking",
            tool_calls=(
                LmsChatToolCall(
                    tool_name="vault-get-file",
                    args_json='{"input_payload": {"file_path": "resume.md"}}',
                    tool_call_id="call-1",
                ),
            ),
        ),
        LmsChatMessage(
            role="tool",
            content='{"path": "resume.md"}',
            tool_name="vault-get-file",
            tool_call_id="call-1",
        ),
    ]


def test_to_sdk_messages_omits_cache_points_from_user_content() -> None:
    """Prompt-cache markers should not leak into LMS-visible user text."""
    from actors.agent import main
    from pydantic_ai.messages import CachePoint, ModelRequest, UserPromptPart

    messages = [
        ModelRequest(parts=[UserPromptPart(content=["hello", CachePoint()])]),
        ModelRequest(parts=[UserPromptPart(content=[CachePoint()])]),
    ]

    result = main._to_sdk_messages(messages)

    assert result == [LmsChatMessage(role="user", content="hello")]


def test_format_user_prompt_places_cachepoint_before_current_instruction() -> None:
    """The current instruction should come after the historical snapshot cache cut."""
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
            system_prompt="",
            profile=MemoryProfileContext(
                operator_name="Operator",
                brain_name="Brain",
                brain_verbosity="normal",
            ),
            focus="current focus",
            dialogue=(
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
    historical_index = prompt.index("historical_snapshot:")
    reference_index = prompt.index("reference_snippets:")
    current_index = prompt.index("Current Instruction:")

    assert prompt[0] == "MAS Context"
    assert prompt.index("profile:") < prompt.index("focus:")
    assert historical_index < cache_index < reference_index < current_index
    assert prompt[-1] == "reaction_to_proposal_token: "
    assert prompt[current_index + 3] == "message: hello"


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
    assert client.prompt == (
        "<metadata>\n"
        "* These results come from the `vault-search-files` tool.\n"
        '* The tool was invoked in "decide" mode.\n'
        "* The model stated its intent as: "
        "<intent>Find Claire's birthday.</intent>\n"
        "</metadata>\n\n"
        "<raw_result>\n"
        '{"items":[]}\n'
        "</raw_result>"
    )


def test_create_runtime_uses_personality_system_prompt() -> None:
    """Runtime creation should render the personality and use it as the system prompt."""
    from actors.agent import main

    class _FakeClient:
        def memory_start_session(self, *, personality: str = "default"):
            return MemorySessionRef(
                session_id="session-1",
                system_prompt="You are Brain, a personal AI system.",
            )

        def describe_capabilities(self):
            return ()

        def list_always_on_capabilities(self):
            return ()

    runtime = main._create_runtime(
        client=_FakeClient(),
        settings=_actor_settings_stub(),
        core_settings=_core_settings_stub("default"),
    )

    assert any(
        "Brain" in str(item)
        for item in runtime.agent._system_prompts  # pyright: ignore[reportPrivateUsage]
    )


def test_create_runtime_uses_configured_tier2_hop_threshold() -> None:
    """Runtime creation should wire the configured Tier 2 hop threshold."""
    from actors.agent import main

    class _FakeClient:
        def memory_start_session(self, *, personality: str = "default"):
            return MemorySessionRef(session_id="session-1", system_prompt="")

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
            core_settings=_core_settings_stub(),
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
            self.messages: tuple[LmsChatMessage, ...] | None = None
            self.tools: tuple[LmsChatToolDefinition, ...] | None = None
            self.timeout_seconds: float | None = None

        def lms_chat_with_tools(
            self,
            *,
            messages: tuple[LmsChatMessage, ...],
            tools: tuple[LmsChatToolDefinition, ...],
            tool_choice: str | dict[str, object] | None = None,
            parallel_tool_calls: bool | None = None,
            allow_text_output: bool = True,
            profile: str = "standard",
            timeout_seconds: float | None = None,
            meta: object | None = None,
        ) -> LmsToolChatResult:
            del tool_choice, parallel_tool_calls, allow_text_output, profile, meta
            self.messages = messages
            self.tools = tools
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
    assert model._client.messages == (  # type: ignore[attr-defined]
        LmsChatMessage(role="system", content="system"),
        LmsChatMessage(role="user", content="hello"),
    )
    assert model._client.tools == (  # type: ignore[attr-defined]
        LmsChatToolDefinition(
            name="vault-get-file",
            description="Read a file.",
            parameters_json_schema={
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
            strict=None,
            sequential=False,
        ),
    )
    assert isinstance(response.parts[0], ToolCallPart)
    assert response.parts[0].tool_name == "vault-get-file"
    assert response.parts[0].tool_call_id == "call-1"


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
                system_prompt="",
                profile=MemoryProfileContext(
                    operator_name="Operator",
                    brain_name="Brain",
                    brain_verbosity="normal",
                ),
                focus="current focus",
                dialogue=(
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
    assert client.recorded == [
        (
            "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "assistant reply",
            "test-model",
            "unit",
            main._estimate_token_count("assistant reply"),
            "standard",
        )
    ]
    assert client.deliveries == [("01ARZ3NDEKTSV4RRFFQ69G5FAV", "turn-outbound", True)]
    assert client.invoked == [
        (
            "attention-notify",
            {
                "actor": "operator",
                "channel": "signal",
                "message": "assistant reply",
            },
            "operator",
            "signal",
        )
    ]


def test_process_instruction_handles_lms_throttle_gracefully() -> None:
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
                system_prompt="",
                profile=MemoryProfileContext(
                    operator_name="Operator",
                    brain_name="Brain",
                    brain_verbosity="normal",
                ),
                focus="current focus",
                dialogue=(
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
    assert client.recorded == [
        (
            "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            main._LMS_THROTTLE_RESPONSE,
            "brain-sdk-lms",
            "brain-sdk",
            main._estimate_token_count(main._LMS_THROTTLE_RESPONSE),
            "standard",
        )
    ]
    assert client.invoked == [
        (
            "attention-notify",
            {
                "actor": "operator",
                "channel": "signal",
                "message": main._LMS_THROTTLE_RESPONSE,
            },
            "operator",
            "signal",
        )
    ]


def test_process_instruction_handles_lms_timeout_gracefully() -> None:
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
                system_prompt="",
                profile=MemoryProfileContext(
                    operator_name="Operator",
                    brain_name="Brain",
                    brain_verbosity="normal",
                ),
                focus="current focus",
                dialogue=(),
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
    assert client.recorded == [
        (
            "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            main._LMS_TIMEOUT_RESPONSE,
            "brain-sdk-lms",
            "brain-sdk",
            main._estimate_token_count(main._LMS_TIMEOUT_RESPONSE),
            "standard",
        )
    ]
    assert client.invoked == [
        (
            "attention-notify",
            {
                "actor": "operator",
                "channel": "signal",
                "message": main._LMS_TIMEOUT_RESPONSE,
            },
            "operator",
            "signal",
        )
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
                    "litellm": {
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


def test_create_runtime_creates_session_and_registers_tools() -> None:
    """Runtime creation should create one session and register all active tools."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.created = 0
            self.described = 0
            self.always_on = 0

        def memory_start_session(
            self, *, personality: str = "default"
        ) -> MemorySessionRef:
            self.created += 1
            return MemorySessionRef(
                session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV", system_prompt=""
            )

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

    runtime = main._create_runtime(
        client=_FakeClient(),  # type: ignore[arg-type]
        settings=_actor_settings_stub(),
        core_settings=_core_settings_stub(),
    )

    assert runtime.session_id == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert isinstance(runtime.model, main._BrainSdkToolModel)
    assert len(runtime.agent._function_toolset.tools) == 3
    assert "attention-notify" not in runtime.turn_state.active_tool_names


def test_runtime_discovery_tools_activate_capabilities_for_prepare_tools() -> None:
    """Discovery should activate matched capabilities for the next prepare_tools call."""
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
            "capability_id": "vault-get-file",
            "required_params": ["file_path"],
            "summary": "Read one markdown file by path.",
        }
    ]
    assert "vault-get-file" in turn_state.active_tool_names

    prepare_tools = main._build_prepare_tools(turn_state=turn_state)
    prepared = asyncio.run(
        prepare_tools(
            None,
            [
                ToolDefinition(name="vault-search-files"),
                ToolDefinition(name="vault-get-file"),
                ToolDefinition(name="attention-notify"),
                ToolDefinition(name=main._DISCOVER_CAPABILITIES_TOOL_NAME),
            ],
        )
    )
    assert [item.name for item in prepared] == [
        "vault-search-files",
        "vault-get-file",
        main._DISCOVER_CAPABILITIES_TOOL_NAME,
    ]


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
            "capability_id": "vault-get-file",
            "required_params": ["file_path"],
            "summary": "Read one markdown file by path.",
        }
    ]
    assert "attention-notify" not in turn_state.active_tool_names

    describe_result = runtime_tools[1].function(
        capability_id="attention-notify",
        call_mode="decide",
        response_detail="Inspect whether this capability can be used right now.",
    )
    assert describe_result == {
        "capability_id": "attention-notify",
        "available": False,
        "reason": "capability is denied for this agent",
    }
    assert "attention-notify" not in turn_state.active_tool_names
