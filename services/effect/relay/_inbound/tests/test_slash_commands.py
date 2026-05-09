"""Slash command handling tests for normalized Relay inbound messages."""

from __future__ import annotations

from lib.shared.envelope import EnvelopeKind, new_meta
from lib.shared.inbound_message import (
    InboundMessage,
    InboundSender,
    InboundSlashCommand,
)
from services.effect.relay._inbound.config import (
    RelayInboundIdentitySettings,
    RelayInboundServiceSettings,
)
from services.effect.relay._inbound.implementation import DefaultRelayInboundService
from services.effect.relay._inbound.tests.test_inbound_service import (
    _FakeCacheService,
    _FakeRelayOutboundService,
    _FakeSignalAdapter,
)
from services.reason.recall.service import InboundInstructionRecord


class _FakeBrainClient:
    """Minimal slash-command client fake."""

    def __init__(self) -> None:
        self.invocations: list[dict[str, object]] = []

    def resolve_slash_command(self, *, name: str):
        return (
            type(
                "Descriptor",
                (),
                {
                    "op_id": "demo-op",
                    "input_schema": {"properties": {"path": {"type": "string"}}},
                    "simple_output_path": "message",
                },
            )()
            if name == "demo"
            else None
        )

    def invoke_op(self, **kwargs):
        self.invocations.append(kwargs)
        return type("Result", (), {"output": {"message": "ok"}})()


class _FakeRecallService:
    """Minimal Recall fake for slash inbound recording."""

    def __init__(self) -> None:
        self.recorded: list[InboundInstructionRecord] = []

    def get_latest_or_create_session(self, *, meta):
        del meta
        return type(
            "Envelope",
            (),
            {
                "ok": True,
                "payload": type(
                    "Payload", (), {"value": type("Session", (), {"id": "session-1"})()}
                )(),
            },
        )()

    def record_inbound_turn(self, *, meta, session_id, message, instruction):
        del meta, session_id, message
        self.recorded.append(instruction)
        return type("Envelope", (), {"ok": True})()


def _meta():
    return new_meta(kind=EnvelopeKind.EVENT, source="test", principal="operator")


def test_normalized_slash_command_is_handled_without_queueing() -> None:
    """Relay should consume DTO slash commands without reparsing raw text."""
    brain = _FakeBrainClient()
    cache = _FakeCacheService()
    service = DefaultRelayInboundService(
        settings=RelayInboundServiceSettings(),
        identity=RelayInboundIdentitySettings(
            operator_contact_e164="+12025550100", default_dial_code="+1"
        ),
        inbound_adapters=(_FakeSignalAdapter(),),
        cache_service=cache,
        outbound_service=_FakeRelayOutboundService(),
        brain_client=brain,  # type: ignore[arg-type]
    )
    message = InboundMessage(
        channel="console",
        message_text="/demo --path /tmp/foo",
        timestamp_ms=1,
        slash_command=InboundSlashCommand(name="demo", args_text="--path /tmp/foo"),
    )

    result = service.ingest_inbound_message(meta=_meta(), message=message)

    assert result.ok is True
    assert result.payload is not None
    assert result.payload.value.queued is False
    assert cache.queue_calls == []
    assert brain.invocations[0]["op_id"] == "demo-op"


def test_slash_command_records_inbound_turn_metadata() -> None:
    """Slash command recording should map inbound DTO fields into Recall metadata."""
    brain = _FakeBrainClient()
    recall = _FakeRecallService()
    service = DefaultRelayInboundService(
        settings=RelayInboundServiceSettings(),
        identity=RelayInboundIdentitySettings(
            operator_contact_e164="+12025550100", default_dial_code="+1"
        ),
        inbound_adapters=(_FakeSignalAdapter(),),
        cache_service=_FakeCacheService(),
        outbound_service=_FakeRelayOutboundService(),
        recall_service=recall,  # type: ignore[arg-type]
        brain_client=brain,  # type: ignore[arg-type]
    )
    message = InboundMessage(
        channel="console",
        sender=InboundSender(e164="+12025550100"),
        message_text="/demo --path /tmp/foo",
        timestamp_ms=1,
        source_device="terminal",
        slash_command=InboundSlashCommand(name="demo", args_text="--path /tmp/foo"),
    )

    result = service.ingest_inbound_message(meta=_meta(), message=message)

    assert result.ok is True
    assert recall.recorded[0].sender_e164 == "+12025550100"
    assert recall.recorded[0].source == "console"
    assert recall.recorded[0].message_text == "/demo --path /tmp/foo"
