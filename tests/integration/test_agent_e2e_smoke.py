"""End-to-end in-process smoke for inbound Signal message to outbound reply."""

from __future__ import annotations

from packages.brain_sdk import CapabilityDescriptor, CapabilitySearchHit
from resources.adapters.litellm import AdapterToolChatResult, AdapterChatToolCall
from tests.helpers.inprocess_core_smoke import run_agent_e2e_smoke


def test_agent_e2e_smoke_runs_inbound_message_to_outbound_reply(tmp_path) -> None:
    """Inbound message, Switchboard poll, MAS/LMS turn, and AR send should all complete."""
    result = run_agent_e2e_smoke(tmp_path=tmp_path)

    assert result.inbound_status_code == 202
    assert result.inbound_body["ok"] is True
    assert result.inbound_body["accepted"] is True
    assert result.response_text == "assistant reply"
    assert result.outbound_signal_messages == (
        {
            "sender_e164": "+17175371552",
            "recipient_e164": "+16104257807",
            "message": "assistant reply",
        },
    )


def test_agent_e2e_smoke_keeps_tool_set_stable_during_discovery(tmp_path) -> None:
    """In-process smoke should keep the callable tool set stable during discovery."""
    result = run_agent_e2e_smoke(
        tmp_path=tmp_path,
        tool_chat_results=(
            AdapterToolChatResult(
                provider="unit",
                model="test-model",
                finish_reason="tool_call",
                text=None,
                tool_calls=(
                    AdapterChatToolCall(
                        tool_name="search_tools",
                        args_json='{"query":"find the resume file","limit":5}',
                        tool_call_id="call-discover",
                    ),
                ),
            ),
            AdapterToolChatResult(
                provider="unit",
                model="test-model",
                finish_reason="stop",
                text="assistant reply",
                tool_calls=(),
            ),
        ),
        capability_search_results=(
            CapabilitySearchHit(
                capability_id="vault-get-file",
                required_params=("file_path",),
                summary="Read one markdown file by path.",
            ),
        ),
        described_capabilities=(
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
        capability_invoke_outputs={"vault-get-file": {"content": "# Resume"}},
    )

    assert result.response_text == "assistant reply"
    assert result.tool_request_tool_names == (
        ("search_tools", "get_tool_info"),
        ("search_tools", "get_tool_info"),
    )
    assert result.outbound_signal_messages == (
        {
            "sender_e164": "+17175371552",
            "recipient_e164": "+16104257807",
            "message": "assistant reply",
        },
    )
