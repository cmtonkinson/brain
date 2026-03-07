"""End-to-end in-process smoke for inbound Signal webhook to outbound reply."""

from __future__ import annotations

from tests.helpers.inprocess_core_smoke import run_agent_e2e_smoke


def test_agent_e2e_smoke_runs_webhook_to_outbound_reply(tmp_path) -> None:
    """Inbound webhook, Switchboard poll, MAS/LMS turn, and AR send should all complete."""
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
