"""Tests for console channel support in Relay inbound service."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.testclient import TestClient

from lib.shared.envelope import EnvelopeKind, new_meta, success
from lib.shared.http.server import create_app
from services.effect.relay._inbound.api import register_routes
from services.effect.relay._inbound.domain import (
    ConsoleEnqueueResult,
    NormalizedOperatorMessage,
)
from services.effect.relay._inbound.service import RelayInboundService


class _FakeRelayInboundService(RelayInboundService):
    """Programmable Relay inbound fake for console route tests."""

    def __init__(self) -> None:
        self.enqueue_calls: list[str] = []
        self.enqueue_result = success(
            meta=_meta(),
            payload=ConsoleEnqueueResult(queued=True, queue_name="console_inbound"),
        )
        self.poll_instruction_result = success(
            meta=_meta(),
            payload=NormalizedOperatorMessage(
                source="console",
                message_text="hello from console",
                timestamp_ms=1000,
            ),
        )

    def ingest_signal_message(self, *, meta, raw_body_json: str):
        raise NotImplementedError

    def enqueue_console_message(
        self, *, meta, message_text: str, slash_authenticity=None
    ):
        del slash_authenticity
        self.enqueue_calls.append(message_text)
        return self.enqueue_result

    def register_signal_callback(self, *, meta):
        raise NotImplementedError

    def poll_operator_instruction(self, *, meta, wait_timeout_seconds: float = 0.0):
        return self.poll_instruction_result

    def health(self, *, meta):
        raise NotImplementedError


def _meta():
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def _client() -> tuple[TestClient, _FakeRelayInboundService]:
    app = create_app()
    router = APIRouter()
    service = _FakeRelayInboundService()
    register_routes(router=router, service=service)
    app.include_router(router)
    return TestClient(app), service


def test_enqueue_console_message_enqueues() -> None:
    """Enqueue route should forward the message and return queued status."""
    client, service = _client()

    response = client.post(
        "/relay/enqueue_console_message",
        json={
            "source": "console",
            "principal": "operator",
            "message_text": "hello brain",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["payload"]["queued"] is True
    assert payload["errors"] == []
    assert service.enqueue_calls == ["hello brain"]


def test_poll_operator_instruction_returns_console_message() -> None:
    """Poll route should return a console-sourced operator instruction."""
    client, service = _client()

    response = client.post(
        "/relay/poll_operator_instruction",
        json={
            "source": "agent",
            "principal": "agent",
            "wait_timeout_seconds": 0.0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["payload"]["source"] == "console"
    assert payload["payload"]["message_text"] == "hello from console"
    assert payload["errors"] == []
