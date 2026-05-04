"""Behavior tests for the Console adapter."""

from __future__ import annotations

import pytest

from lib.shared.auth.slash_authenticity import SlashAuthenticityProof
from lib.shared.envelope import EnvelopeKind, new_meta
from resources.adapters.console.adapter import (
    ConsoleAdapterInternalError,
    ConsoleInboundCallbackResult,
    ConsoleInboundPayload,
)
from resources.adapters.console.config import ConsoleAdapterSettings
from resources.adapters.console.console_adapter import InProcessConsoleAdapter


def _adapter() -> InProcessConsoleAdapter:
    return InProcessConsoleAdapter(settings=ConsoleAdapterSettings())


def _meta():
    return new_meta(kind=EnvelopeKind.COMMAND, source="console", principal="operator")


def test_submit_without_callback_raises_internal_error() -> None:
    """The adapter rejects submissions until a callback has been registered."""
    adapter = _adapter()
    with pytest.raises(ConsoleAdapterInternalError):
        adapter.submit(
            meta=_meta(),
            payload=ConsoleInboundPayload(message_text="hi"),
        )


def test_submit_dispatches_payload_to_registered_callback() -> None:
    """The registered callback receives the parsed payload verbatim."""
    captured: list[ConsoleInboundPayload] = []

    def callback(*, meta, payload):
        del meta
        captured.append(payload)
        return ConsoleInboundCallbackResult(queued=True, queue_name="console_inbound")

    adapter = _adapter()
    adapter.register_callback(callback=callback)

    proof = SlashAuthenticityProof(hmac_b64="abc", timestamp_ms=1, nonce="n1")
    payload = ConsoleInboundPayload(
        message_text="/workspace-register --path /tmp/foo",
        slash_authenticity=proof,
    )
    result = adapter.submit(meta=_meta(), payload=payload)

    assert len(captured) == 1
    assert captured[0].message_text == "/workspace-register --path /tmp/foo"
    assert captured[0].slash_authenticity == proof
    assert result.queued is True
    assert result.queue_name == "console_inbound"


def test_health_reports_callback_state() -> None:
    """Health string reflects whether a callback has been registered."""
    adapter = _adapter()
    assert "callback=unconfigured" in adapter.health().detail

    adapter.register_callback(
        callback=lambda *, meta, payload: ConsoleInboundCallbackResult(  # noqa: ARG005
            queued=True, queue_name="x"
        )
    )
    assert "callback=configured" in adapter.health().detail
