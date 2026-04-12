"""Unit tests for Brain SDK call wrappers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from packages.brain_sdk.errors import BrainTransportError, BrainValidationError
from packages.brain_shared.http.errors import HttpStatusError


def _meta() -> dict[str, object]:
    from packages.brain_sdk.meta import build_envelope_meta

    return build_envelope_meta(source="tests", principal="operator")


def _fake_http(response: object) -> MagicMock:
    """Return a mock HttpClient that returns response from get_json/post_json."""
    http = MagicMock()
    http.get_json.return_value = response
    http.post_json.return_value = response
    return http


def test_call_core_health_success() -> None:
    """Core health wrapper should return mapped component dictionaries."""
    from packages.brain_sdk.calls import call_core_health

    http = _fake_http(
        {
            "ready": True,
            "services": {"svc": {"ready": True, "detail": "ok"}},
            "resources": {"res": {"ready": False, "detail": "degraded"}},
        }
    )

    result = call_core_health(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
    )

    assert result.ready is True
    assert result.services["svc"].detail == "ok"
    assert result.resources["res"].ready is False


def test_call_core_health_transport_error() -> None:
    """Core health wrapper should raise BrainTransportError on HTTP failure."""
    from packages.brain_sdk.calls import call_core_health

    transport_http = MagicMock()
    transport_http.get_json.side_effect = HttpStatusError(
        message="unavailable",
        method="GET",
        url="http://brain-core/health",
        retryable=True,
        status_code=503,
        response_body="down",
        response_headers={},
    )

    with pytest.raises(BrainTransportError):
        call_core_health(
            http=transport_http,
            metadata=_meta(),
            timeout_seconds=1.0,
        )


def test_call_capabilities_describe_success() -> None:
    """Capability-describe wrapper should return typed descriptors."""
    from packages.brain_sdk.calls import call_capabilities_describe

    http = _fake_http(
        {
            "capabilities": [
                {
                    "capability_id": "demo-echo",
                    "kind": "logic_skill",
                    "version": "1.0.0",
                    "summary": "Echo one value.",
                    "input_schema": {"value": "string"},
                    "output_schema": {"value": "string"},
                    "autonomy": 0,
                    "requires_approval": False,
                    "side_effects": [],
                    "required_capabilities": [],
                }
            ],
            "errors": [],
        }
    )

    result = call_capabilities_describe(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
    )

    assert len(result) == 1
    assert result[0].capability_id == "demo-echo"
    assert result[0].kind == "logic_skill"


def test_call_capabilities_list_always_on_success() -> None:
    """Always-on capability wrapper should return typed descriptors."""
    from packages.brain_sdk.calls import call_capabilities_list_always_on

    http = _fake_http(
        {
            "capabilities": [
                {
                    "capability_id": "vault-search-files",
                    "kind": "native_op",
                    "version": "1.0.0",
                    "summary": "Search files.",
                    "input_schema": {"query": "string"},
                    "output_schema": {"results": "array[string]"},
                    "autonomy": 0,
                    "requires_approval": False,
                    "side_effects": [],
                    "required_capabilities": [],
                }
            ],
            "errors": [],
        }
    )

    result = call_capabilities_list_always_on(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
    )

    assert len(result) == 1
    assert result[0].capability_id == "vault-search-files"


def test_call_capabilities_search_success() -> None:
    """Capability-search wrapper should return compact typed hits."""
    from packages.brain_sdk.calls import call_capabilities_search

    http = _fake_http(
        {
            "results": [
                {
                    "capability_id": "vault-get-file",
                    "required_params": ["file_path"],
                    "summary": "Read a file.",
                }
            ],
            "errors": [],
        }
    )

    result = call_capabilities_search(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        query="read a markdown file",
        limit=5,
    )

    assert result == (
        type(result[0])(
            capability_id="vault-get-file",
            required_params=("file_path",),
            summary="Read a file.",
        ),
    )


def test_call_capability_describe_success() -> None:
    """Capability-describe-one wrapper should return a single typed descriptor."""
    from packages.brain_sdk.calls import call_capability_describe

    http = _fake_http(
        {
            "capability": {
                "capability_id": "vault-get-file",
                "kind": "native_op",
                "version": "1.0.0",
                "summary": "Read a file.",
                "input_schema": {"file_path": "string"},
                "output_schema": {"content": "string"},
                "autonomy": 0,
                "requires_approval": False,
                "side_effects": [],
                "required_capabilities": [],
            },
            "errors": [],
        }
    )

    result = call_capability_describe(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        capability_id="vault-get-file",
    )

    assert result.capability_id == "vault-get-file"


def test_call_capability_invoke_success() -> None:
    """Capability-invoke wrapper should decode output JSON and policy."""
    from packages.brain_sdk.calls import call_capability_invoke

    http = _fake_http(
        {
            "output_json": '{"ok":true,"value":"done"}',
            "policy": {
                "decision_id": "dec-1",
                "allowed": True,
                "reason_codes": ["allow"],
                "obligations": [],
                "proposal_id": "prop-1",
            },
            "errors": [],
        }
    )

    result = call_capability_invoke(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        capability_id="demo-echo",
        input_payload={"value": "x"},
    )

    assert result.output == {"ok": True, "value": "done"}
    assert result.policy.allowed is True
    assert result.policy.decision_id == "dec-1"


def test_call_capability_invoke_autogenerates_invocation_id() -> None:
    """Capability invoke should auto-generate invocation_id when omitted."""
    from packages.brain_sdk.calls import call_capability_invoke

    http = _fake_http(
        {
            "output_json": "{}",
            "policy": {
                "decision_id": "dec-1",
                "allowed": True,
                "reason_codes": [],
                "obligations": [],
                "proposal_id": "",
            },
            "errors": [],
        }
    )

    call_capability_invoke(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        capability_id="attention-notify",
        input_payload={"message": "hello", "actor": "operator", "channel": "signal"},
        actor="operator",
        channel="signal",
        invocation_id="",
    )

    body = http.post_json.call_args.kwargs["json"]
    assert isinstance(body["invocation_id"], str)
    assert len(body["invocation_id"]) == 26


def test_call_capability_invoke_includes_reply_and_reaction_proposal_tokens() -> None:
    """Capability invoke should pass structured approval correlators through CES."""
    from packages.brain_sdk.calls import call_capability_invoke

    http = _fake_http(
        {
            "output_json": "{}",
            "policy": {
                "decision_id": "dec-1",
                "allowed": True,
                "reason_codes": [],
                "obligations": [],
                "proposal_id": "",
            },
            "errors": [],
        }
    )

    call_capability_invoke(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        capability_id="vault-move-path",
        input_payload={"source_path": "a", "target_path": "b"},
        actor="operator",
        channel="signal",
        reply_to_proposal_token="tok-quote",
        reaction_to_proposal_token="tok-react",
    )

    body = http.post_json.call_args.kwargs["json"]
    assert body["reply_to_proposal_token"] == "tok-quote"
    assert body["reaction_to_proposal_token"] == "tok-react"


def test_call_lms_chat_success() -> None:
    """LMS chat wrapper should return the typed chat payload."""
    from packages.brain_sdk.calls import call_lms_chat

    http = _fake_http(
        {
            "payload": {
                "text": "hello",
                "provider": "openai",
                "model": "gpt-test",
            },
            "errors": [],
        }
    )

    result = call_lms_chat(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        prompt="hi",
    )

    assert result.text == "hello"
    assert result.provider == "openai"
    assert result.model == "gpt-test"


def test_call_lms_chat_with_tools_success() -> None:
    """Tool-capable LMS chat wrapper should return typed tool call payloads."""
    from packages.brain_sdk.calls import (
        LmsChatMessage,
        LmsChatToolDefinition,
        call_lms_chat_with_tools,
    )

    http = _fake_http(
        {
            "payload": {
                "provider": "openai",
                "model": "gpt-test",
                "finish_reason": "tool_call",
                "text": None,
                "tool_calls": [
                    {
                        "tool_name": "demo-tool",
                        "args_json": '{"value":"x"}',
                        "tool_call_id": "call-1",
                    }
                ],
            },
            "errors": [],
        }
    )

    result = call_lms_chat_with_tools(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        messages=(LmsChatMessage(role="user", content="hello"),),
        tools=(
            LmsChatToolDefinition(
                name="demo-tool",
                parameters_json_schema={"type": "object"},
            ),
        ),
        tool_choice="auto",
        parallel_tool_calls=True,
    )

    assert result.provider == "openai"
    assert result.finish_reason == "tool_call"
    assert result.tool_calls[0].tool_name == "demo-tool"


def test_call_memory_assemble_context_success() -> None:
    """MAS assemble-context wrapper should return the typed context payload."""
    from packages.brain_sdk.calls import call_memory_assemble_context

    http = _fake_http(
        {
            "payload": {
                "profile": {
                    "operator_name": "Operator",
                    "brain_name": "Brain",
                    "brain_verbosity": "normal",
                },
                "focus": "current focus",
                "dialogue": [{"role": "user", "content": "hello", "is_summary": False}],
                "reference_snippets": ["snippet"],
            },
            "errors": [],
        }
    )

    result = call_memory_assemble_context(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        message="hello",
    )

    assert result.profile.brain_name == "Brain"
    assert result.focus == "current focus"
    assert result.dialogue[0].content == "hello"
    assert result.reference_snippets == ("snippet",)


def test_call_memory_record_inbound_turn_success() -> None:
    """MAS inbound-record wrapper should return the typed turn payload."""
    from packages.brain_sdk.calls import call_memory_record_inbound_turn
    from packages.brain_sdk.calls import SwitchboardOperatorInstruction

    http = _fake_http(
        {
            "payload": {
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "direction": "inbound",
                "content": "hello",
                "role": "user",
                "model": None,
                "provider": None,
                "token_count": 3,
                "reasoning_level": None,
                "trace_id": "trace",
                "principal": "operator",
                "created_at": "2026-04-12T00:00:00+00:00",
            },
            "errors": [],
        }
    )

    result = call_memory_record_inbound_turn(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        message="hello",
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
            reply_to_proposal_token=None,
            reaction_to_proposal_token=None,
        ),
    )

    assert result.id == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert result.direction == "inbound"
    assert result.content == "hello"
    assert (
        http.post_json.call_args.kwargs["json"]["instruction"]["sender_e164"]
        == "+12025550100"
    )


def test_call_memory_assemble_snapshot_success() -> None:
    """MAS snapshot wrapper should return the typed historical context payload."""
    from packages.brain_sdk.calls import call_memory_assemble_snapshot

    http = _fake_http(
        {
            "payload": {
                "profile": {
                    "operator_name": "Operator",
                    "brain_name": "Brain",
                    "brain_verbosity": "normal",
                },
                "focus": "current focus",
                "dialogue": [
                    {"role": "assistant", "content": "prior", "is_summary": False}
                ],
                "reference_snippets": ["snippet"],
            },
            "errors": [],
        }
    )

    result = call_memory_assemble_snapshot(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
    )

    assert result.profile.brain_name == "Brain"
    assert result.dialogue[0].content == "prior"
    assert result.reference_snippets == ("snippet",)


def test_call_memory_create_session_success() -> None:
    """MAS create-session wrapper should return the new session identifier."""
    from packages.brain_sdk.calls import call_memory_create_session

    http = _fake_http(
        {
            "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "errors": [],
        }
    )

    result = call_memory_create_session(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
    )

    assert result.session_id == "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def test_call_memory_get_latest_or_create_session_success() -> None:
    """MAS get-latest-or-create wrapper should return the resolved session id."""
    from packages.brain_sdk.calls import call_memory_get_latest_or_create_session

    http = _fake_http(
        {
            "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "errors": [],
        }
    )

    result = call_memory_get_latest_or_create_session(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
    )

    assert result.session_id == "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def test_call_memory_record_response_success() -> None:
    """MAS record-response wrapper should return the response boolean."""
    from packages.brain_sdk.calls import call_memory_record_response

    http = _fake_http({"payload": True, "errors": []})

    result = call_memory_record_response(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        content="assistant reply",
        model="test-model",
        provider="unit",
        token_count=42,
        reasoning_level="standard",
    )

    assert result is True


def test_call_memory_record_outbound_candidate_success() -> None:
    """MAS outbound-candidate wrapper should return the typed turn payload."""
    from packages.brain_sdk.calls import call_memory_record_outbound_candidate

    http = _fake_http(
        {
            "payload": {
                "id": "turn-outbound",
                "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "direction": "outbound",
                "content": "assistant reply",
                "role": "assistant",
                "model": "test-model",
                "provider": "unit",
                "token_count": 42,
                "reasoning_level": "standard",
                "trace_id": "trace",
                "principal": "operator",
                "created_at": "2026-04-12T00:00:00+00:00",
            },
            "errors": [],
        }
    )

    result = call_memory_record_outbound_candidate(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        content="assistant reply",
        model="test-model",
        provider="unit",
        token_count=42,
        reasoning_level="standard",
    )

    assert result.id == "turn-outbound"
    assert result.direction == "outbound"
    assert result.content == "assistant reply"


def test_call_memory_record_outbound_delivery_success() -> None:
    """MAS outbound-delivery wrapper should return the delivery boolean."""
    from packages.brain_sdk.calls import call_memory_record_outbound_delivery

    http = _fake_http({"payload": True, "errors": []})

    result = call_memory_record_outbound_delivery(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        turn_id="turn-outbound",
        delivered=True,
    )

    assert result is True


def test_route_wrapper_raises_typed_domain_error() -> None:
    """Route wrappers should map response errors to typed SDK domain errors."""
    from packages.brain_sdk.calls import call_lms_chat

    http = _fake_http(
        {
            "payload": None,
            "errors": [
                {
                    "code": "validation_error",
                    "message": "prompt is required",
                    "category": "validation",
                    "retryable": False,
                    "metadata": {},
                }
            ],
        }
    )

    with pytest.raises(BrainValidationError):
        call_lms_chat(
            http=http,
            metadata=_meta(),
            timeout_seconds=1.0,
            prompt="",
        )


def test_call_switchboard_poll_operator_instruction_success() -> None:
    """Switchboard poll wrapper should return the typed dequeued message."""
    from packages.brain_sdk.calls import call_switchboard_poll_operator_instruction

    http = _fake_http(
        {
            "payload": {
                "sender_e164": "+12025550100",
                "message_text": "hello",
                "timestamp_ms": 1,
                "source_device": "1",
                "source": "signal",
                "group_id": None,
                "quote_target_timestamp_ms": None,
                "reaction_target_timestamp_ms": None,
                "reaction_emoji": "👍",
                "approval_intent": "approve",
                "reply_to_proposal_token": "tok-quote",
                "reaction_to_proposal_token": "tok-react",
            },
            "errors": [],
        }
    )

    result = call_switchboard_poll_operator_instruction(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        wait_timeout_seconds=2.0,
    )

    assert result is not None
    assert result.message_text == "hello"
    assert result.sender_e164 == "+12025550100"
    assert result.reaction_emoji == "👍"
    assert result.approval_intent == "approve"
    assert result.reply_to_proposal_token == "tok-quote"
    assert result.reaction_to_proposal_token == "tok-react"
