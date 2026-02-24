"""Tests for Switchboard HTTP webhook ingress app behavior."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from packages.brain_shared.envelope import EnvelopeKind, failure, new_meta, success
from packages.brain_shared.errors import dependency_error, policy_error
from services.action.switchboard.config import SwitchboardServiceSettings
from services.action.switchboard.domain import IngestResult, NormalizedSignalMessage
from services.action.switchboard.http_ingress import create_switchboard_webhook_app
from services.action.switchboard.service import SwitchboardService


@dataclass(frozen=True)
class _IngestCall:
    raw_body_json: str
    header_timestamp: str
    header_signature: str


class _FakeSwitchboardService(SwitchboardService):
    """Switchboard fake with programmable ingest responses for HTTP tests."""

    def __init__(self) -> None:
        self.ingest_calls: list[_IngestCall] = []
        self.ingest_result = success(
            meta=_meta(),
            payload=IngestResult(
                accepted=True,
                queued=True,
                queue_name="signal_inbound",
                reason="accepted",
                message=NormalizedSignalMessage(
                    sender_e164="+12025550100",
                    message_text="hello",
                    timestamp_ms=1,
                    source_device="1",
                    source="+12025550100",
                ),
            ),
        )

    def ingest_signal_webhook(
        self,
        *,
        meta,
        raw_body_json: str,
        header_timestamp: str,
        header_signature: str,
    ):
        del meta
        self.ingest_calls.append(
            _IngestCall(
                raw_body_json=raw_body_json,
                header_timestamp=header_timestamp,
                header_signature=header_signature,
            )
        )
        return self.ingest_result

    def register_signal_webhook(self, *, meta, callback_url: str):
        del meta, callback_url
        raise NotImplementedError

    def health(self, *, meta):
        del meta
        raise NotImplementedError


def _meta():
    """Build valid envelope metadata for Switchboard test responses."""
    return new_meta(kind=EnvelopeKind.EVENT, source="test", principal="operator")


def _client() -> tuple[TestClient, _FakeSwitchboardService]:
    """Build one FastAPI test client and backing fake service."""
    service = _FakeSwitchboardService()
    settings = SwitchboardServiceSettings(webhook_path="/v1/inbound/signal/webhook")
    app = create_switchboard_webhook_app(service=service, settings=settings)
    return TestClient(app), service


def test_http_ingress_forwards_body_and_signature_headers() -> None:
    """POST callback should forward raw JSON and signature headers to service."""
    client, service = _client()
    response = client.post(
        "/v1/inbound/signal/webhook",
        json={"data": {"message": "hello"}},
        headers={
            "X-Brain-Timestamp": "123",
            "X-Brain-Signature": "abc",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["ok"] is True
    assert len(service.ingest_calls) == 1
    call = service.ingest_calls[0]
    assert call.raw_body_json == '{"data":{"message":"hello"}}'
    assert call.header_timestamp == "123"
    assert call.header_signature == "abc"


def test_http_ingress_requires_signature_headers() -> None:
    """Missing signature headers should fail with HTTP 400."""
    client, _service = _client()
    response = client.post(
        "/v1/inbound/signal/webhook",
        json={"data": {"message": "hello"}},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False


def test_http_ingress_returns_forbidden_for_policy_error() -> None:
    """Policy failures should return HTTP 403 with structured error payload."""
    client, service = _client()
    service.ingest_result = failure(
        meta=_meta(),
        errors=[policy_error("signature mismatch")],
    )
    response = client.post(
        "/v1/inbound/signal/webhook",
        json={},
        headers={
            "X-Brain-Timestamp": "1",
            "X-Brain-Signature": "sig",
        },
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["ok"] is False
    assert payload["errors"][0]["category"] == "policy"


def test_http_ingress_returns_service_unavailable_for_dependency_error() -> None:
    """Dependency failures should map to HTTP 503 from webhook endpoint."""
    client, service = _client()
    service.ingest_result = failure(
        meta=_meta(),
        errors=[dependency_error("redis unavailable")],
    )
    response = client.post(
        "/v1/inbound/signal/webhook",
        json={},
        headers={
            "X-Brain-Timestamp": "1",
            "X-Brain-Signature": "sig",
        },
    )

    assert response.status_code == 503
