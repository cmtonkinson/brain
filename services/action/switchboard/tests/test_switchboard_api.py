"""HTTP route adapter tests for Switchboard Service."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter
from fastapi.testclient import TestClient

from packages.brain_shared.envelope import EnvelopeKind, failure, new_meta, success
from packages.brain_shared.errors import validation_error
from packages.brain_shared.http.server import create_app
from services.action.switchboard.api import register_routes
from services.action.switchboard.domain import (
    NormalizedOperatorMessage,
)
from services.action.switchboard.service import SwitchboardService


@dataclass(frozen=True)
class _PollCall:
    """Captured poll invocation arguments."""

    wait_timeout_seconds: float
    source: str
    principal: str


class _FakeSwitchboardService(SwitchboardService):
    """Programmable Switchboard fake for Core route-adapter tests."""

    def __init__(self) -> None:
        self.poll_calls: list[_PollCall] = []
        self.poll_result = success(
            meta=_meta(),
            payload=NormalizedOperatorMessage(
                sender_e164="+12025550100",
                message_text="hello",
                timestamp_ms=1,
                source_device="1",
                source="signal",
                reaction_emoji=None,
                approval_intent=None,
            ),
        )

    def ingest_signal_message(
        self,
        *,
        meta,
        raw_body_json: str,
    ):
        del meta, raw_body_json
        raise NotImplementedError

    def enqueue_console_message(self, *, meta, message_text: str):
        del meta, message_text
        raise NotImplementedError

    def register_signal_callback(self, *, meta):
        del meta
        raise NotImplementedError

    def poll_console_response(self, *, meta, wait_timeout_seconds: float = 0.0):
        del meta, wait_timeout_seconds
        raise NotImplementedError

    def poll_operator_instruction(
        self,
        *,
        meta,
        wait_timeout_seconds: float = 0.0,
    ):
        self.poll_calls.append(
            _PollCall(
                wait_timeout_seconds=wait_timeout_seconds,
                source=meta.source,
                principal=meta.principal,
            )
        )
        return self.poll_result

    def health(self, *, meta):
        del meta
        raise NotImplementedError


def _meta():
    """Build valid envelope metadata for Switchboard route-test responses."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def _client() -> tuple[TestClient, _FakeSwitchboardService]:
    """Create one FastAPI test client with the Switchboard route adapter mounted."""
    app = create_app()
    router = APIRouter()
    service = _FakeSwitchboardService()
    register_routes(router=router, service=service)
    app.include_router(router)
    return TestClient(app), service


def test_poll_operator_instruction_route_forwards_request_and_returns_payload() -> None:
    """Poll route should forward arguments and serialize the queued message."""
    client, service = _client()

    response = client.post(
        "/switchboard/poll_operator_instruction",
        json={
            "source": "agent",
            "principal": "agent",
            "wait_timeout_seconds": 1.5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["payload"]["message_text"] == "hello"
    assert payload["errors"] == []
    assert service.poll_calls == [
        _PollCall(wait_timeout_seconds=1.5, source="agent", principal="agent")
    ]


def test_poll_operator_instruction_route_maps_service_errors() -> None:
    """Poll route should serialize envelope errors when the service fails."""
    client, service = _client()
    service.poll_result = failure(
        meta=_meta(),
        errors=[validation_error("wait_timeout_seconds must be >= 0")],
    )

    response = client.post(
        "/switchboard/poll_operator_instruction",
        json={},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["payload"] is None
    assert payload["errors"][0]["category"] == "validation"
