"""Fast agent-turn regression tests over a mock Core HTTP transport."""

from __future__ import annotations

from unittest.mock import MagicMock

from actors.agent import main as agent_main
from tests.helpers.agent_turn_harness import AgentTurnScenario, run_agent_turn_scenario


def test_agent_turn_harness_routes_final_reply_via_attention_notify() -> None:
    """One full harnessed turn should persist response and invoke attention-notify."""
    result = run_agent_turn_scenario(AgentTurnScenario())

    assert result.response_text == "assistant reply"
    assert [call.path for call in result.calls] == [
        "/memory/get_latest_or_create_session",
        "/capabilities/describe",
        "/capabilities/always-on",
        "/memory/assemble_context",
        "/lms/chat-with-tools",
        "/memory/record_response",
        "/capabilities/invoke",
    ]
    invoke_call = result.calls[-1]
    assert invoke_call.body["capability_id"] == "attention-notify"
    assert invoke_call.body["input_payload"] == {
        "actor": "operator",
        "channel": "signal",
        "message": "assistant reply",
    }
    assert invoke_call.body["invocation_id"] != ""


def test_agent_turn_harness_logs_notify_failures_without_failing_turn() -> None:
    """Outbound notify failures should be logged while preserving turn completion."""
    scenario = AgentTurnScenario(
        capability_invoke_errors=[
            {
                "code": "dependency_unavailable",
                "message": "signal send failed with status 400",
                "category": "dependency",
                "retryable": True,
                "metadata": {"adapter": "adapter_signal"},
            }
        ]
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
