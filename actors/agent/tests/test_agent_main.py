"""Behavior tests for the Brain Agent process entrypoint."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from packages.brain_shared.config import ActorSettings, CoreSettings
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


def test_load_system_prompt_reads_colocated_prompt_file() -> None:
    """System prompt should load from the colocated prompt file on disk."""
    from actors.agent import main

    prompt = main._load_system_prompt()

    assert prompt != ""
    assert "tool" in prompt.lower()
    assert "Respond with JSON only." not in prompt


def test_load_system_prompt_appends_profile_extension_when_present() -> None:
    """System prompt loader should append operator-supplied prompt text verbatim."""
    from actors.agent import main

    prompt = main._load_system_prompt(system_prompt_append="Extra operator prompt.")

    assert prompt.endswith("Extra operator prompt.")


def test_load_prompt_file_reads_compressor_prompt_from_disk() -> None:
    """Prompt-file helper should load the colocated compressor prompt text."""
    from actors.agent import main

    prompt = main._load_prompt_file(main._COMPRESS_SYSTEM_PROMPT_PATH)

    assert prompt == main._COMPRESS_SYSTEM_PROMPT
    assert "tool result compressor" in prompt.lower()


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

    settings = ActorSettings()
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


def test_create_runtime_uses_core_profile_system_prompt_append() -> None:
    """Runtime creation should append core profile prompt text to the base prompt."""
    from actors.agent import main

    class _FakeClient:
        def memory_get_latest_or_create_session(self):
            return MemorySessionRef(session_id="session-1")

        def describe_capabilities(self):
            return ()

        def list_always_on_capabilities(self):
            return ()

    runtime = main._create_runtime(
        client=_FakeClient(),
        settings=ActorSettings(),
        core_settings=CoreSettings(
            profile={"system_prompt_append": "Extra operator prompt."}
        ),
    )

    assert any(
        "Extra operator prompt." in str(item)
        for item in runtime.agent._system_prompts  # pyright: ignore[reportPrivateUsage]
    )


def test_create_runtime_uses_configured_tier2_hop_threshold() -> None:
    """Runtime creation should wire the configured Tier 2 hop threshold."""
    from actors.agent import main

    class _FakeClient:
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

    settings = ActorSettings()
    settings.agent.tool_loop_tier2_hop_threshold = 5
    original = main._build_history_processor
    main._build_history_processor = _fake_build_history_processor  # type: ignore[assignment]
    try:
        main._create_runtime(
            client=_FakeClient(),
            settings=settings,
            core_settings=CoreSettings(),
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
                reaction_emoji=None,
                approval_intent=None,
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
        core_settings=CoreSettings(),
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
