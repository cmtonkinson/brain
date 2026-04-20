"""Tests for slash command parsing and handling in Switchboard."""

from __future__ import annotations

from unittest.mock import MagicMock


from packages.brain_sdk.calls import (
    CapabilityDescriptor,
    CapabilityInvokeResult,
    PolicyDecision,
)
from packages.brain_shared.envelope import EnvelopeKind, new_meta, success
from services.action.attention_router.domain import RouteNotificationResult
from services.action.switchboard.config import (
    SwitchboardIdentitySettings,
    SwitchboardServiceSettings,
)
from services.action.switchboard.implementation import (
    DefaultSwitchboardService,
    _parse_slash_command,
    _parse_slash_args,
    _render_slash_output,
)


# ---------------------------------------------------------------------------
# Pure-function parsing tests
# ---------------------------------------------------------------------------


def test_parse_slash_command_simple() -> None:
    assert _parse_slash_command("/help") == ("help", "")


def test_parse_slash_command_with_args() -> None:
    assert _parse_slash_command("/ls path/to/dir") == ("ls", "path/to/dir")


def test_parse_slash_command_lowercases_name() -> None:
    assert _parse_slash_command("/Help") == ("help", "")


def test_parse_slash_command_not_a_command() -> None:
    assert _parse_slash_command("hello world") is None


def test_parse_slash_command_empty_string() -> None:
    assert _parse_slash_command("") is None


def test_parse_slash_command_leading_whitespace() -> None:
    assert _parse_slash_command("  /status  ") == ("status", "")


def test_parse_slash_args_empty() -> None:
    assert _parse_slash_args("", None) == {}


def test_parse_slash_args_single_key_value() -> None:
    result = _parse_slash_args("--path /tmp/foo", None)
    assert result == {"path": "/tmp/foo"}


def test_parse_slash_args_boolean_flag() -> None:
    result = _parse_slash_args("--verbose", None)
    assert result == {"verbose": True}


def test_parse_slash_args_multiple() -> None:
    result = _parse_slash_args("--key1 val1 --key2 val2", None)
    assert result == {"key1": "val1", "key2": "val2"}


def test_parse_slash_args_hyphenated_key_becomes_underscore() -> None:
    result = _parse_slash_args("--dry-run", None)
    assert result == {"dry_run": True}


def test_render_slash_output_none() -> None:
    assert _render_slash_output(None, None) == "Done."


def test_render_slash_output_string() -> None:
    assert _render_slash_output("hello", None) == "hello"


def test_render_slash_output_simple_path() -> None:
    output = {"result": {"text": "found it"}}
    assert _render_slash_output(output, "result.text") == "found it"


def test_render_slash_output_dict_no_path() -> None:
    import json

    output = {"key": "value"}
    rendered = _render_slash_output(output, None)
    assert json.loads(rendered) == output


# ---------------------------------------------------------------------------
# _handle_slash_command behavior tests
# ---------------------------------------------------------------------------


def _meta():
    return new_meta(kind=EnvelopeKind.EVENT, source="switchboard", principal="operator")


def _make_descriptor(capability_id: str = "test-cap") -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        kind="logic_skill",
        version="1.0.0",
        summary="A test capability.",
        input_schema=None,
        output_schema=None,
        autonomy=0,
        requires_approval=False,
        side_effects=(),
        required_capabilities=(),
        simple_output_path=None,
    )


def _make_service(
    brain_client=None,
    attention_router=None,
) -> DefaultSwitchboardService:
    cache = MagicMock()
    cache.push_queue.return_value = success(meta=_meta(), payload=1)

    ars = attention_router or MagicMock()
    ars.route_notification.return_value = success(
        meta=_meta(),
        payload=RouteNotificationResult(decision="sent", delivered=True, detail="ok"),
    )

    adapter = MagicMock()
    adapter.health.return_value = MagicMock(adapter_ready=True, detail="ok")

    return DefaultSwitchboardService(
        settings=SwitchboardServiceSettings(),
        identity=SwitchboardIdentitySettings(
            operator_signal_contact_e164="+12025550100",
            default_dial_code="+1",
        ),
        adapter=adapter,
        cache_service=cache,
        attention_router_service=ars,
        brain_client=brain_client,
    )


def test_handle_slash_command_found_invokes_capability_and_routes() -> None:
    """Found command → invoke_capability called → output routed via ARS."""
    descriptor = _make_descriptor("test-cap")
    invoke_result = CapabilityInvokeResult(
        output="capability output",
        policy=PolicyDecision(
            decision_id="d1",
            allowed=True,
            reason_codes=(),
            obligations=(),
            proposal_id="",
        ),
    )

    brain_client = MagicMock()
    brain_client.resolve_slash_command.return_value = descriptor
    brain_client.invoke_capability.return_value = invoke_result

    ars = MagicMock()
    ars.route_notification.return_value = success(
        meta=_meta(),
        payload=RouteNotificationResult(decision="sent", delivered=True, detail="ok"),
    )

    service = _make_service(brain_client=brain_client, attention_router=ars)

    result = service._handle_slash_command(
        meta=_meta(),
        command_name="test",
        args_text="",
        source="console",
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.queued is False

    brain_client.resolve_slash_command.assert_called_once_with(name="test")
    brain_client.invoke_capability.assert_called_once_with(
        capability_id="test-cap",
        input_payload={},
        actor="operator",
        channel="console",
    )
    ars.route_notification.assert_called_once()
    call_kwargs = ars.route_notification.call_args.kwargs
    assert call_kwargs["channel"] == "console"
    assert call_kwargs["message"] == "capability output"
    assert call_kwargs["force"] is True


def test_handle_slash_command_not_found_routes_error_no_invoke() -> None:
    """Unknown command → error message routed; invoke_capability not called."""
    brain_client = MagicMock()
    brain_client.resolve_slash_command.return_value = None

    ars = MagicMock()
    ars.route_notification.return_value = success(
        meta=_meta(),
        payload=RouteNotificationResult(decision="sent", delivered=True, detail="ok"),
    )

    service = _make_service(brain_client=brain_client, attention_router=ars)

    result = service._handle_slash_command(
        meta=_meta(),
        command_name="unknown",
        args_text="",
        source="console",
    )

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.queued is False

    brain_client.invoke_capability.assert_not_called()
    ars.route_notification.assert_called_once()
    call_kwargs = ars.route_notification.call_args.kwargs
    assert "Unknown command" in call_kwargs["message"]
    assert "/unknown" in call_kwargs["message"]


def test_handle_slash_command_invoke_failure_routes_error() -> None:
    """Invoke exception → error message routed; still returns queued=False."""
    descriptor = _make_descriptor("test-cap")
    brain_client = MagicMock()
    brain_client.resolve_slash_command.return_value = descriptor
    brain_client.invoke_capability.side_effect = RuntimeError("timeout")

    ars = MagicMock()
    ars.route_notification.return_value = success(
        meta=_meta(),
        payload=RouteNotificationResult(decision="sent", delivered=True, detail="ok"),
    )

    service = _make_service(brain_client=brain_client, attention_router=ars)

    result = service._handle_slash_command(
        meta=_meta(),
        command_name="test",
        args_text="",
        source="console",
    )

    assert result.ok is True
    assert result.payload.value.queued is False
    call_kwargs = ars.route_notification.call_args.kwargs
    assert "/test failed" in call_kwargs["message"]


def test_handle_slash_command_no_brain_client_routes_error() -> None:
    """No brain_client → error message routed; still returns queued=False."""
    ars = MagicMock()
    ars.route_notification.return_value = success(
        meta=_meta(),
        payload=RouteNotificationResult(decision="sent", delivered=True, detail="ok"),
    )

    service = _make_service(brain_client=None, attention_router=ars)

    result = service._handle_slash_command(
        meta=_meta(),
        command_name="help",
        args_text="",
        source="console",
    )

    assert result.ok is True
    assert result.payload.value.queued is False
    ars.route_notification.assert_called_once()


# ---------------------------------------------------------------------------
# enqueue_console_message branch tests
# ---------------------------------------------------------------------------


def test_enqueue_console_regular_message_queues() -> None:
    """Non-slash message → queued=True via CAS."""
    brain_client = MagicMock()
    service = _make_service(brain_client=brain_client)
    service._cache_service.push_queue.return_value = success(meta=_meta(), payload=1)

    result = service.enqueue_console_message(meta=_meta(), message_text="hello brain")

    assert result.ok is True
    assert result.payload.value.queued is True
    brain_client.resolve_slash_command.assert_not_called()


def test_enqueue_console_slash_message_not_queued() -> None:
    """Slash message → queued=False; resolved inline."""
    descriptor = _make_descriptor("help-cap")
    invoke_result = CapabilityInvokeResult(
        output="Available commands: /help",
        policy=PolicyDecision(
            decision_id="d1",
            allowed=True,
            reason_codes=(),
            obligations=(),
            proposal_id="",
        ),
    )

    brain_client = MagicMock()
    brain_client.resolve_slash_command.return_value = descriptor
    brain_client.invoke_capability.return_value = invoke_result

    ars = MagicMock()
    ars.route_notification.return_value = success(
        meta=_meta(),
        payload=RouteNotificationResult(decision="sent", delivered=True, detail="ok"),
    )

    service = _make_service(brain_client=brain_client, attention_router=ars)

    result = service.enqueue_console_message(meta=_meta(), message_text="/help")

    assert result.ok is True
    assert result.payload.value.queued is False
    # CAS push should NOT have been called for the slash message
    service._cache_service.push_queue.assert_not_called()
