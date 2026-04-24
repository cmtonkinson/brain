"""Tests for Relay outbound HTTP API routes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.testclient import TestClient

from lib.shared.envelope import EnvelopeKind, new_meta, success
from lib.shared.http.server import create_app
from services.effect.relay._outbound.api import register_routes
from services.effect.relay._outbound.domain import ConsoleResponseMessage
from services.effect.relay._outbound.service import RelayOutboundService


class _FakeRelayOutboundService(RelayOutboundService):
    """Programmable Relay outbound fake for API route tests."""

    def __init__(self) -> None:
        self.poll_response_result = success(
            meta=_meta(),
            payload=ConsoleResponseMessage(
                message="Brain says hello",
                timestamp_ms=2000,
            ),
        )

    def route_notification(self, *, meta, **_kwargs):
        raise NotImplementedError

    def route_approval_notification(self, *, meta, approval):
        raise NotImplementedError

    def flush_batch(self, *, meta, **_kwargs):
        raise NotImplementedError

    def health(self, *, meta):
        raise NotImplementedError

    def correlate_approval_response(self, *, meta, **_kwargs):
        raise NotImplementedError

    def resolve_approval_notification_proposal_token(self, *, meta, **_kwargs):
        raise NotImplementedError

    def poll_console_response(self, *, meta, wait_timeout_seconds: float = 0.0):
        return self.poll_response_result


def _meta():
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def _client() -> tuple[TestClient, _FakeRelayOutboundService]:
    app = create_app()
    router = APIRouter()
    service = _FakeRelayOutboundService()
    register_routes(router=router, service=service)
    app.include_router(router)
    return TestClient(app), service


def test_poll_console_response_returns_brain_message() -> None:
    """Console response poll should return the Brain response text."""
    client, service = _client()

    response = client.post(
        "/relay/poll_console_response",
        json={
            "source": "console",
            "principal": "operator",
            "wait_timeout_seconds": 0.0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["payload"]["message"] == "Brain says hello"
    assert payload["payload"]["timestamp_ms"] == 2000
    assert payload["errors"] == []


def test_poll_console_response_returns_null_when_empty() -> None:
    """Console response poll should return null payload when queue is empty."""
    client, service = _client()
    service.poll_response_result = success(meta=_meta(), payload=None)

    response = client.post(
        "/relay/poll_console_response",
        json={
            "source": "console",
            "principal": "operator",
            "wait_timeout_seconds": 0.0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["payload"] is None
    assert payload["errors"] == []
