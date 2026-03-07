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
