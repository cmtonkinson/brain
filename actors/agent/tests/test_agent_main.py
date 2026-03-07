"""Behavior tests for the Brain Agent process entrypoint."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

from packages.brain_sdk import (
    CapabilityDescriptor,
    LmsChatResult,
    MemoryContextBlock,
    MemoryDialogueTurn,
    MemoryProfileContext,
    MemorySessionRef,
    SwitchboardOperatorInstruction,
)


def test_resolve_config_path_uses_env_override(monkeypatch) -> None:
    """Config-path helper should return a Path only when the env var is set."""
    from actors.agent import main

    monkeypatch.setenv("BRAIN_ACTORS_CONFIG_FILE", "/tmp/actors.yaml")

    assert main._resolve_config_path() == Path("/tmp/actors.yaml")


def test_load_system_prompt_reads_colocated_prompt_file() -> None:
    """System prompt should load from the colocated prompt file on disk."""
    from actors.agent import main

    prompt = main._load_system_prompt()

    assert "Respond with JSON only." in prompt
    assert '"kind":"tool_call"' in prompt


def test_configure_logging_uses_configured_level(monkeypatch) -> None:
    """Logging helper should honor the configured string log level."""
    from actors.agent import main

    basic_config = MagicMock()
    monkeypatch.setattr(main.logging, "basicConfig", basic_config)

    main._configure_logging(level="DEBUG")

    basic_config.assert_called_once()
    assert basic_config.call_args.kwargs["level"] == main.logging.DEBUG


def test_parse_model_output_supports_tool_calls() -> None:
    """Model-output parser should normalize valid tool-call JSON replies."""
    from actors.agent import main

    result = main._parse_model_output(
        '{"kind":"tool_call","tool_name":"vault-get-file","input_payload":{"file_path":"x.md"}}'
    )

    assert result.kind == "tool_call"
    assert result.tool_name == "vault-get-file"
    assert result.input_payload == {"file_path": "x.md"}


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

    result = tools[0].function(input_payload={"value": "x"})

    assert result == {"ok": True}
    assert client.calls == [("demo-tool", {"value": "x"}, "operator", "signal")]


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
            self._runtime.model_driver.last_chat_result = LmsChatResult(
                text='{"kind":"final","content":"assistant reply"}',
                provider="unit",
                model="test-model",
            )
            return _FakeRunResult(output="assistant reply")

    client = _FakeClient()
    runtime = main._AgentRuntime(
        client=client,  # type: ignore[arg-type]
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        turn_state=main._TurnState(),
        model_driver=main._BrainSdkModelDriver.__new__(main._BrainSdkModelDriver),
        agent=None,  # type: ignore[arg-type]
    )
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
                "recipient_e164": "+12025550100",
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

        def lms_chat(self, *, prompt: str, profile: str = "standard") -> LmsChatResult:
            del prompt, profile
            return LmsChatResult(
                text='{"kind":"final","content":"done"}',
                provider="unit",
                model="test-model",
            )

    runtime = main._create_runtime(client=_FakeClient())  # type: ignore[arg-type]

    assert runtime.session_id == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert len(runtime.agent._function_toolset.tools) == 1
