"""Fast agent-turn regression tests over a mock Core HTTP transport."""

from __future__ import annotations

from unittest.mock import MagicMock

from actors.agent import main as agent_main
from lib.sdk import (
    CapabilityDescriptor,
    CapabilitySearchHit,
    LmsChatToolCall,
    LmsToolChatResult,
)
from tests.helpers.agent_turn_harness import AgentTurnScenario, run_agent_turn_scenario


def test_agent_turn_harness_routes_final_reply_via_attention_notify() -> None:
    """One full harnessed turn should persist response and invoke attention-notify."""
    result = run_agent_turn_scenario(AgentTurnScenario())

    assert result.response_text == "assistant reply"
    assert [call.path for call in result.calls] == [
        "/memory/get_latest_or_create_session",
        "/capabilities/describe",
        "/capabilities/always-on",
        "/capabilities/tool-system-hints",
        "/memory/assemble_context",
        "/lms/chat-with-tools",
        "/capabilities/invoke",
    ]
    invoke_call = result.calls[6]
    assert invoke_call.body["capability_id"] == "attention-notify"
    assert invoke_call.body["input_payload"]["actor"] == "operator"
    assert invoke_call.body["input_payload"]["channel"] == "signal"
    assert invoke_call.body["input_payload"]["message"] == "assistant reply"
    assert invoke_call.body["input_payload"]["conversational_memory"] == {
        "session_id": invoke_call.body["input_payload"]["conversational_memory"][
            "session_id"
        ],
        "model": "test-model",
        "provider": "unit",
        "token_count": agent_main._estimate_token_count("assistant reply"),
        "reasoning_level": "standard",
    }
    assert (
        invoke_call.body["input_payload"]["conversational_memory"]["session_id"] != ""
    )
    assert invoke_call.body["invocation_id"] != ""


def test_agent_turn_harness_preserves_trace_linkage_for_final_notify() -> None:
    """Final attention notify should stay on the same turn trace as LMS tool chat."""
    result = run_agent_turn_scenario(AgentTurnScenario())

    assemble_call = next(
        call for call in result.calls if call.path == "/memory/assemble_context"
    )
    lms_call = next(
        call for call in result.calls if call.path == "/lms/chat-with-tools"
    )
    notify_call = next(
        call for call in reversed(result.calls) if call.path == "/capabilities/invoke"
    )

    assert notify_call.path == "/capabilities/invoke"
    assert notify_call.body["capability_id"] == "attention-notify"
    assert assemble_call.body["trace_id"] == lms_call.body["trace_id"]
    assert lms_call.body["trace_id"] == notify_call.body["trace_id"]
    assert notify_call.body["parent_id"] == lms_call.body["envelope_id"]


def test_agent_turn_harness_logs_notify_failures_without_failing_turn() -> None:
    """Outbound notify failures should be logged while preserving turn completion."""
    scenario = AgentTurnScenario(
        capability_invoke_errors={
            "attention-notify": [
                {
                    "code": "dependency_unavailable",
                    "message": "signal send failed with status 400",
                    "category": "dependency",
                    "retryable": True,
                    "metadata": {"adapter": "adapter_signal"},
                }
            ]
        }
    )
    exception_log = MagicMock()
    original = agent_main._LOGGER.exception
    agent_main._LOGGER.exception = exception_log

    try:
        result = run_agent_turn_scenario(scenario)
    finally:
        agent_main._LOGGER.exception = original

    assert result.response_text == "assistant reply"
    exception_log.assert_called_once()
    assert exception_log.call_args.args[0] == "brain agent outbound notify failed"


def test_agent_turn_harness_keeps_tool_set_stable_after_discovery() -> None:
    """One turn should keep the callable tool set stable after discovery."""
    vault_search = CapabilityDescriptor(
        capability_id="vault-search-files",
        kind="native_op",
        version="1.0.0",
        summary="Search markdown files.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        autonomy=0,
        requires_approval=False,
        side_effects=(),
        required_capabilities=(),
    )
    vault_get = CapabilityDescriptor(
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
    scenario = AgentTurnScenario(
        capabilities=(vault_search, vault_get),
        always_on_capabilities=(vault_search,),
        search_results=(
            CapabilitySearchHit(
                capability_id="vault-get-file",
                required_params=("file_path",),
                summary="Read one markdown file by path.",
            ),
        ),
        described_capabilities={"vault-get-file": vault_get},
        chat_results=(
            LmsToolChatResult(
                provider="unit",
                model="test-model",
                finish_reason="tool_call",
                text=None,
                tool_calls=(
                    LmsChatToolCall(
                        tool_name="search_tools",
                        args_json='{"query":"find the resume file","limit":5}',
                        tool_call_id="call-discover",
                    ),
                ),
            ),
            LmsToolChatResult(
                provider="unit",
                model="test-model",
                finish_reason="stop",
                text="assistant reply",
                tool_calls=(),
            ),
        ),
        capability_invoke_outputs={
            "vault-get-file": {"content": "# Resume"},
            "attention-notify": {"decision": "sent"},
        },
    )

    result = run_agent_turn_scenario(scenario)

    assert result.response_text == "assistant reply"
    assert [call.path for call in result.calls] == [
        "/memory/get_latest_or_create_session",
        "/capabilities/describe",
        "/capabilities/always-on",
        "/capabilities/tool-system-hints",
        "/memory/assemble_context",
        "/lms/chat-with-tools",
        "/capabilities/search",
        "/lms/chat-with-tools",
        "/capabilities/invoke",
    ]
    first_lms_call = result.calls[5]
    second_lms_call = result.calls[7]
    assert [
        tool["name"] for tool in first_lms_call.body["inference_request"]["tools"]
    ] == [
        "vault-search-files",
        "search_tools",
        "get_tool_info",
    ]
    assert [
        tool["name"] for tool in second_lms_call.body["inference_request"]["tools"]
    ] == [
        "vault-search-files",
        "search_tools",
        "get_tool_info",
    ]
    assert not any(
        call.path == "/capabilities/invoke"
        and call.body.get("capability_id") == "vault-get-file"
        for call in result.calls
    )


def test_agent_turn_harness_keeps_deny_listed_capabilities_out_of_next_round_tools() -> (
    None
):
    """Discovery results should not cause deny-listed capabilities to become callable."""
    vault_search = CapabilityDescriptor(
        capability_id="vault-search-files",
        kind="native_op",
        version="1.0.0",
        summary="Search markdown files.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        autonomy=0,
        requires_approval=False,
        side_effects=(),
        required_capabilities=(),
    )
    vault_get = CapabilityDescriptor(
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
    scenario = AgentTurnScenario(
        capabilities=(vault_search, vault_get),
        always_on_capabilities=(vault_search,),
        search_results=(
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
        ),
        described_capabilities={"vault-get-file": vault_get},
        chat_results=(
            LmsToolChatResult(
                provider="unit",
                model="test-model",
                finish_reason="tool_call",
                text=None,
                tool_calls=(
                    LmsChatToolCall(
                        tool_name="search_tools",
                        args_json='{"query":"send signal message","limit":5}',
                        tool_call_id="call-discover",
                    ),
                ),
            ),
            LmsToolChatResult(
                provider="unit",
                model="test-model",
                finish_reason="stop",
                text="assistant reply",
                tool_calls=(),
            ),
        ),
    )

    result = run_agent_turn_scenario(scenario)

    assert result.response_text == "assistant reply"
    second_lms_call = result.calls[7]
    tool_names = [
        tool["name"] for tool in second_lms_call.body["inference_request"]["tools"]
    ]
    assert "attention-notify" not in tool_names
    assert "vault-get-file" not in tool_names
