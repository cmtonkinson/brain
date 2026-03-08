"""Behavior tests for the Brain Agent process entrypoint."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

from packages.brain_shared.config import ActorSettings
from packages.brain_sdk import (
    BrainDependencyError,
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


def test_resolve_config_path_uses_env_override(monkeypatch) -> None:
    """Config-path helper should return a Path only when the env var is set."""
    from actors.agent import main

    monkeypatch.setenv("BRAIN_ACTORS_CONFIG_FILE", "/tmp/actors.yaml")

    assert main._resolve_config_path() == Path("/tmp/actors.yaml")


def test_load_system_prompt_reads_colocated_prompt_file() -> None:
    """System prompt should load from the colocated prompt file on disk."""
    from actors.agent import main

    prompt = main._load_system_prompt()

    assert prompt != ""
    assert "tool" in prompt.lower()
    assert "Respond with JSON only." not in prompt


def test_configure_logging_uses_configured_level(monkeypatch) -> None:
    """Logging helper should honor the configured string log level."""
    from actors.agent import main

    basic_config = MagicMock()
    monkeypatch.setattr(main.logging, "basicConfig", basic_config)

    main._configure_logging(level="DEBUG")

    basic_config.assert_called_once()
    assert basic_config.call_args.kwargs["level"] == main.logging.DEBUG


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


def test_build_capability_tools_invokes_sdk_client() -> None:
    """Capability tool wrappers should route tool calls through Brain SDK only."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object], str, str]] = []

        def invoke_capability(
            self,
            *,
            capability_id: str,
            input_payload: dict[str, object],
            actor: str,
            channel: str,
        ):
            self.calls.append((capability_id, input_payload, actor, channel))
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
    assert client.calls == [("demo-tool", {"value": "x"}, "operator", "signal")]


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
        ):
            del capability_id, input_payload, actor, channel
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

        def lms_chat_with_tools(
            self,
            *,
            messages: tuple[LmsChatMessage, ...],
            tools: tuple[LmsChatToolDefinition, ...],
            tool_choice: str | dict[str, object] | None = None,
            parallel_tool_calls: bool | None = None,
            allow_text_output: bool = True,
            profile: str = "standard",
            meta: object | None = None,
        ) -> LmsToolChatResult:
            del tool_choice, parallel_tool_calls, allow_text_output, profile, meta
            self.messages = messages
            self.tools = tools
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

    model = main._BrainSdkToolModel(client=_FakeClient())  # type: ignore[arg-type]
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
                    }
                },
                "required": ["input_payload"],
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
            self.assembled: list[tuple[str, str]] = []
            self.recorded: list[tuple[str, str, str, str, int, str]] = []
            self.invoked: list[tuple[str, dict[str, object], str, str]] = []

        def memory_assemble_context(
            self, *, session_id: str, message: str
        ) -> MemoryContextBlock:
            self.assembled.append((session_id, message))
            return MemoryContextBlock(
                profile=MemoryProfileContext(
                    operator_name="Operator",
                    brain_name="Brain",
                    brain_verbosity="normal",
                ),
                focus="current focus",
                dialogue=(
                    MemoryDialogueTurn(
                        role="user",
                        content=message,
                        is_summary=False,
                    ),
                ),
                reference_snippets=(),
            )

        def memory_record_response(
            self,
            *,
            session_id: str,
            content: str,
            model: str,
            provider: str,
            token_count: int,
            reasoning_level: str,
        ) -> bool:
            self.recorded.append(
                (session_id, content, model, provider, token_count, reasoning_level)
            )
            return True

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
            ),
        )
    )

    assert response == "assistant reply"
    assert client.assembled == [("01ARZ3NDEKTSV4RRFFQ69G5FAV", "hello")]
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
            self.recorded: list[tuple[str, str, str, str, int, str]] = []
            self.invoked: list[tuple[str, dict[str, object], str, str]] = []

        def memory_assemble_context(
            self, *, session_id: str, message: str
        ) -> MemoryContextBlock:
            return MemoryContextBlock(
                profile=MemoryProfileContext(
                    operator_name="Operator",
                    brain_name="Brain",
                    brain_verbosity="normal",
                ),
                focus="current focus",
                dialogue=(
                    MemoryDialogueTurn(
                        role="user",
                        content=message,
                        is_summary=False,
                    ),
                ),
                reference_snippets=(),
            )

        def memory_record_response(
            self,
            *,
            session_id: str,
            content: str,
            model: str,
            provider: str,
            token_count: int,
            reasoning_level: str,
        ) -> bool:
            self.recorded.append(
                (session_id, content, model, provider, token_count, reasoning_level)
            )
            return True

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


def test_create_runtime_creates_session_and_registers_tools() -> None:
    """Runtime creation should create one session and register all active tools."""
    from actors.agent import main

    class _FakeClient:
        def __init__(self) -> None:
            self.created = 0
            self.described = 0
            self.always_on = 0

        def memory_get_latest_or_create_session(self) -> MemorySessionRef:
            self.created += 1
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

    runtime = main._create_runtime(
        client=_FakeClient(),  # type: ignore[arg-type]
        settings=ActorSettings(),
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
    )
    assert discover_result == [
        {
            "capability_id": "vault-get-file",
            "required_params": ["file_path"],
            "summary": "Read one markdown file by path.",
        }
    ]
    assert "attention-notify" not in turn_state.active_tool_names

    describe_result = runtime_tools[1].function(capability_id="attention-notify")
    assert describe_result == {
        "capability_id": "attention-notify",
        "available": False,
        "reason": "capability is denied for this agent",
    }
    assert "attention-notify" not in turn_state.active_tool_names
