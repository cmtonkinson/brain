"""Unit tests for Brain SDK call wrappers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lib.sdk.errors import BrainTransportError, BrainValidationError
from lib.shared.http.errors import HttpStatusError
from lib.shared.language_model import InferenceToolDefinition
from tests.helpers.inference_request import make_inference_request


def _meta() -> dict[str, object]:
    from lib.sdk.meta import build_envelope_meta

    return build_envelope_meta(source="tests", principal="operator")


def _fake_http(response: object) -> MagicMock:
    """Return a mock HttpClient that returns response from get_json/post_json."""
    http = MagicMock()
    http.get_json.return_value = response
    http.post_json.return_value = response
    return http


def test_call_core_health_success() -> None:
    """Core health wrapper should return mapped component dictionaries."""
    from lib.sdk.calls import call_core_health

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
    from lib.sdk.calls import call_core_health

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


def test_call_ops_describe_success() -> None:
    """Op-describe wrapper should return typed descriptors."""
    from lib.sdk.calls import call_ops_describe

    http = _fake_http(
        {
            "ops": [
                {
                    "op_id": "demo-echo",
                    "kind": "logic",
                    "version": "1.0.0",
                    "summary": "Echo one value.",
                    "input_schema": {"value": "string"},
                    "output_schema": {"value": "string"},
                    "effect": "execute",
                    "approval": "never",
                    "required_ops": [],
                }
            ],
            "errors": [],
        }
    )

    result = call_ops_describe(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
    )

    assert len(result) == 1
    assert result[0].op_id == "demo-echo"
    assert result[0].kind == "logic"


def test_call_ops_list_always_on_success() -> None:
    """Always-on op wrapper should return typed descriptors."""
    from lib.sdk.calls import call_ops_list_always_on

    http = _fake_http(
        {
            "ops": [
                {
                    "op_id": "vault-search-files",
                    "kind": "native",
                    "version": "1.0.0",
                    "summary": "Search files.",
                    "input_schema": {"query": "string"},
                    "output_schema": {"results": "array[string]"},
                    "effect": "read",
                    "approval": "never",
                    "required_ops": [],
                }
            ],
            "errors": [],
        }
    )

    result = call_ops_list_always_on(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
    )

    assert len(result) == 1
    assert result[0].op_id == "vault-search-files"


def test_call_ops_search_success() -> None:
    """Op-search wrapper should return compact typed hits."""
    from lib.sdk.calls import call_ops_search

    http = _fake_http(
        {
            "results": [
                {
                    "op_id": "vault-get-file",
                    "required_params": ["file_path"],
                    "summary": "Read a file.",
                }
            ],
            "errors": [],
        }
    )

    result = call_ops_search(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        query="read a markdown file",
        limit=5,
    )

    assert result == (
        type(result[0])(
            op_id="vault-get-file",
            required_params=("file_path",),
            summary="Read a file.",
        ),
    )


def test_call_ops_tool_system_hints_success() -> None:
    """Tool-system hint wrapper should return compact typed hints."""
    from lib.sdk.calls import call_ops_tool_system_hints

    http = _fake_http(
        {
            "systems": [
                {
                    "system_id": "service_vault",
                    "label": "Vault Service",
                    "summary": "Personal Knowledge Base access.",
                    "kind": "core",
                    "ready": None,
                    "tool_count": None,
                },
                {
                    "system_id": "filesystem-ro",
                    "label": "filesystem-ro",
                    "summary": "read access to home",
                    "kind": "mcp",
                    "ready": True,
                    "tool_count": 4,
                },
            ],
            "errors": [],
        }
    )

    result = call_ops_tool_system_hints(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
    )

    assert len(result) == 2
    assert result[0].system_id == "service_vault"
    assert result[1].kind == "mcp"
    assert result[1].tool_count == 4


def test_call_op_describe_success() -> None:
    """Op-describe-one wrapper should return a single typed descriptor."""
    from lib.sdk.calls import call_op_describe

    http = _fake_http(
        {
            "op": {
                "op_id": "vault-get-file",
                "kind": "native",
                "version": "1.0.0",
                "summary": "Read a file.",
                "input_schema": {"file_path": "string"},
                "output_schema": {"content": "string"},
                "effect": "read",
                "approval": "never",
                "required_ops": [],
            },
            "errors": [],
        }
    )

    result = call_op_describe(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        op_id="vault-get-file",
    )

    assert result.op_id == "vault-get-file"


def test_call_op_invoke_success() -> None:
    """Op-invoke wrapper should decode output JSON and policy."""
    from lib.sdk.calls import call_op_invoke

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

    result = call_op_invoke(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        op_id="demo-echo",
        input_payload={"value": "x"},
    )

    assert result.output == {"ok": True, "value": "done"}
    assert result.policy.allowed is True
    assert result.policy.decision_id == "dec-1"


def test_call_op_invoke_autogenerates_invocation_id() -> None:
    """Op invoke should auto-generate invocation_id when omitted."""
    from lib.sdk.calls import call_op_invoke

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

    call_op_invoke(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        op_id="relay-notify",
        input_payload={"message": "hello", "actor": "operator", "channel": "signal"},
        actor="operator",
        channel="signal",
        invocation_id="",
    )

    body = http.post_json.call_args.kwargs["json"]
    assert isinstance(body["invocation_id"], str)
    assert len(body["invocation_id"]) == 26


def test_call_op_invoke_includes_reply_and_reaction_proposal_tokens() -> None:
    """Op invoke should pass structured approval correlators through Execution."""
    from lib.sdk.calls import call_op_invoke

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

    call_op_invoke(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        op_id="vault-move-path",
        input_payload={"source_path": "a", "target_path": "b"},
        actor="operator",
        channel="signal",
        reply_to_proposal_token="tok-quote",
        reaction_to_proposal_token="tok-react",
    )

    body = http.post_json.call_args.kwargs["json"]
    assert body["reply_to_proposal_token"] == "tok-quote"
    assert body["reaction_to_proposal_token"] == "tok-react"


def test_call_language_chat_success() -> None:
    """Language chat wrapper should return the typed chat payload."""
    from lib.sdk.calls import call_language_chat

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

    result = call_language_chat(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        prompt="hi",
    )

    assert result.text == "hello"
    assert result.provider == "openai"
    assert result.model == "gpt-test"


def test_call_language_chat_with_tools_success() -> None:
    """Tool-capable Language chat wrapper should return typed tool call payloads."""
    from lib.sdk.calls import call_language_chat_with_tools

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

    result = call_language_chat_with_tools(
        http=http,
        metadata=_meta(),
        timeout_seconds=1.0,
        inference_request=make_inference_request(
            tools=(
                InferenceToolDefinition(
                    name="demo-tool",
                    input_schema={"type": "object"},
                ),
            )
        ),
    )

    assert result.provider == "openai"
    assert result.finish_reason == "tool_call"
    assert result.tool_calls[0].tool_name == "demo-tool"


def test_call_memory_assemble_context_success() -> None:
    """Recall assemble-context wrapper should return the typed turn-context payload."""
    from lib.sdk.calls import call_memory_assemble_context

    http = _fake_http(
        {
            "payload": {
                "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "inbound_turn": {
                    "id": "turn-inbound",
                    "session_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                    "direction": "inbound",
                    "content": "hello",
                    "role": "user",
                    "model": None,
                    "provider": None,
                    "token_count": 3,
                    "reasoning_level": None,
                    "trace_id": "trace",
                    "conversation_episode_id": "episode",
                    "principal": "operator",
                    "created_at": "2026-04-12T00:00:00+00:00",
                },
                "context": {
                    "current_focus": "current focus",
                    "recent_conversation_summary": "prior summary",
                    "recent_turns": [
                        {"role": "user", "content": "hello", "is_summary": False}
                    ],
                    "reference_snippets": ["snippet"],
                },
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

    assert result.session_id == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert result.inbound_turn.content == "hello"
    assert result.context.current_focus == "current focus"
    assert result.context.recent_conversation_summary == "prior summary"
    assert result.context.recent_turns[0].content == "hello"
    assert result.context.reference_snippets == ("snippet",)


def test_call_memory_record_inbound_turn_success() -> None:
    """Recall inbound-record wrapper should return the typed turn payload."""
    from lib.sdk.calls import call_memory_record_inbound_turn
    from lib.sdk.calls import RelayOperatorInstruction

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
                "conversation_episode_id": "episode",
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
        instruction=RelayOperatorInstruction(
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
    assert result.conversation_episode_id == "episode"
    assert (
        http.post_json.call_args.kwargs["json"]["instruction"]["sender_e164"]
        == "+12025550100"
    )


def test_call_memory_assemble_snapshot_success() -> None:
    """Recall snapshot wrapper should return the typed historical context payload."""
    from lib.sdk.calls import call_memory_assemble_snapshot

    http = _fake_http(
        {
            "payload": {
                "current_focus": "current focus",
                "recent_conversation_summary": "prior summary",
                "recent_turns": [
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

    assert result.current_focus == "current focus"
    assert result.recent_conversation_summary == "prior summary"
    assert result.recent_turns[0].content == "prior"
    assert result.reference_snippets == ("snippet",)


def test_call_memory_create_session_success() -> None:
    """Recall create-session wrapper should return the new session identifier."""
    from lib.sdk.calls import call_memory_create_session

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
    """Recall get-latest-or-create wrapper should return the resolved session id."""
    from lib.sdk.calls import call_memory_get_latest_or_create_session

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
    """Recall record-response wrapper should return the response boolean."""
    from lib.sdk.calls import call_memory_record_response

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
    """Recall outbound-candidate wrapper should return the typed turn payload."""
    from lib.sdk.calls import call_memory_record_outbound_candidate

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
                "conversation_episode_id": "episode",
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
    """Recall outbound-delivery wrapper should return the delivery boolean."""
    from lib.sdk.calls import call_memory_record_outbound_delivery

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
    from lib.sdk.calls import call_language_chat

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
        call_language_chat(
            http=http,
            metadata=_meta(),
            timeout_seconds=1.0,
            prompt="",
        )


def test_call_relay_poll_operator_instruction_success() -> None:
    """Relay inbound poll wrapper should return the typed dequeued message."""
    from lib.sdk.calls import call_relay_poll_operator_instruction

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

    result = call_relay_poll_operator_instruction(
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


# ---------------------------------------------------------------------------
# _post_json OTel span annotation
# ---------------------------------------------------------------------------


def test_post_json_annotates_span_when_observability_enabled() -> None:
    """_post_json should create a sdk.* span with input/output when OTel active."""
    from unittest.mock import patch, MagicMock
    from lib.sdk.calls import _post_json

    http = _fake_http({"result": "ok"})
    mock_span = MagicMock()
    mock_span.set_attribute = MagicMock()

    mock_tracer = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__ = lambda s: mock_span
    mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(
        return_value=False
    )

    with (
        patch(
            "lib.shared.observability.is_observability_enabled",
            return_value=True,
        ),
        patch(
            "lib.shared.observability.is_llm_content_capture_enabled",
            return_value=True,
        ),
        patch("opentelemetry.trace.get_tracer", return_value=mock_tracer),
    ):
        result = _post_json(
            operation="test.op",
            http=http,
            url="/test",
            body={"key": "value"},
            timeout_seconds=1.0,
        )

    assert result == {"result": "ok"}
    mock_tracer.start_as_current_span.assert_called_once_with("sdk.test.op")
    calls = {c.args[0]: c.args[1] for c in mock_span.set_attribute.call_args_list}
    assert "langfuse.observation.input" in calls
    assert '"key"' in calls["langfuse.observation.input"]
    assert "langfuse.observation.output" in calls
    assert '"result"' in calls["langfuse.observation.output"]


def test_post_json_skips_span_when_observability_disabled() -> None:
    """_post_json should call through without a span when observability is off."""
    from unittest.mock import patch
    from lib.sdk.calls import _post_json

    http = _fake_http({"result": "ok"})

    with patch(
        "lib.shared.observability.is_observability_enabled",
        return_value=False,
    ):
        result = _post_json(
            operation="test.op",
            http=http,
            url="/test",
            body={"key": "value"},
            timeout_seconds=1.0,
        )

    assert result == {"result": "ok"}
    http.post_json.assert_called_once()


def test_post_json_omits_content_when_capture_disabled() -> None:
    """_post_json span should exist but have no input/output when capture off."""
    from unittest.mock import patch, MagicMock
    from lib.sdk.calls import _post_json

    http = _fake_http({"result": "ok"})
    mock_span = MagicMock()
    mock_span.set_attribute = MagicMock()

    mock_tracer = MagicMock()
    mock_tracer.start_as_current_span.return_value.__enter__ = lambda s: mock_span
    mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(
        return_value=False
    )

    with (
        patch(
            "lib.shared.observability.is_observability_enabled",
            return_value=True,
        ),
        patch(
            "lib.shared.observability.is_llm_content_capture_enabled",
            return_value=False,
        ),
        patch("opentelemetry.trace.get_tracer", return_value=mock_tracer),
    ):
        result = _post_json(
            operation="test.op",
            http=http,
            url="/test",
            body={"key": "value"},
            timeout_seconds=1.0,
        )

    assert result == {"result": "ok"}
    set_keys = [c.args[0] for c in mock_span.set_attribute.call_args_list]
    assert "langfuse.observation.input" not in set_keys
    assert "langfuse.observation.output" not in set_keys
