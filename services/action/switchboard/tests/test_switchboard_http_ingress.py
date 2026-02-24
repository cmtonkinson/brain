"""Tests for Switchboard HTTP webhook ingress server behavior."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from urllib import error as urllib_error
from urllib import request as urllib_request

from packages.brain_shared.envelope import EnvelopeKind, failure, new_meta, success
from packages.brain_shared.errors import dependency_error, policy_error
from services.action.switchboard.config import SwitchboardServiceSettings
from services.action.switchboard.domain import IngestResult, NormalizedSignalMessage
from services.action.switchboard.http_ingress import SwitchboardWebhookHttpServer
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


def _free_port() -> int:
    """Reserve and return one available local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_http_ingress_forwards_body_and_signature_headers() -> None:
    """POST callback should forward raw JSON and signature headers to service."""
    service = _FakeSwitchboardService()
    port = _free_port()
    settings = SwitchboardServiceSettings(
        webhook_bind_host="127.0.0.1",
        webhook_bind_port=port,
        webhook_path="/switchboard/signal",
    )
    server = SwitchboardWebhookHttpServer(service=service, settings=settings)
    server.start()
    try:
        request = urllib_request.Request(
            url=f"http://127.0.0.1:{port}/switchboard/signal",
            data=b'{"data":{"message":"hello"}}',
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Signature-Timestamp": "123",
                "X-Signature": "abc",
            },
        )
        with urllib_request.urlopen(request, timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
            status = response.status
    finally:
        server.close()

    assert status == 202
    assert payload["ok"] is True
    assert len(service.ingest_calls) == 1
    call = service.ingest_calls[0]
    assert call.raw_body_json == '{"data":{"message":"hello"}}'
    assert call.header_timestamp == "123"
    assert call.header_signature == "abc"


def test_http_ingress_returns_forbidden_for_policy_error() -> None:
    """Policy failures should return HTTP 403 with structured error payload."""
    service = _FakeSwitchboardService()
    service.ingest_result = failure(
        meta=_meta(),
        errors=[policy_error("signature mismatch")],
    )
    port = _free_port()
    settings = SwitchboardServiceSettings(
        webhook_bind_host="127.0.0.1",
        webhook_bind_port=port,
        webhook_path="/switchboard/signal",
    )
    server = SwitchboardWebhookHttpServer(service=service, settings=settings)
    server.start()
    try:
        request = urllib_request.Request(
            url=f"http://127.0.0.1:{port}/switchboard/signal",
            data=b"{}",
            method="POST",
        )
        try:
            urllib_request.urlopen(request, timeout=2.0)
        except urllib_error.HTTPError as exc:
            status = exc.code
            payload = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("expected HTTPError")
    finally:
        server.close()

    assert status == 403
    assert payload["ok"] is False
    assert payload["errors"][0]["category"] == "policy"


def test_http_ingress_returns_service_unavailable_for_dependency_error() -> None:
    """Dependency failures should map to HTTP 503 from webhook endpoint."""
    service = _FakeSwitchboardService()
    service.ingest_result = failure(
        meta=_meta(),
        errors=[dependency_error("redis unavailable")],
    )
    port = _free_port()
    settings = SwitchboardServiceSettings(
        webhook_bind_host="127.0.0.1",
        webhook_bind_port=port,
        webhook_path="/switchboard/signal",
    )
    server = SwitchboardWebhookHttpServer(service=service, settings=settings)
    server.start()
    try:
        request = urllib_request.Request(
            url=f"http://127.0.0.1:{port}/switchboard/signal",
            data=b"{}",
            method="POST",
        )
        try:
            urllib_request.urlopen(request, timeout=2.0)
        except urllib_error.HTTPError as exc:
            status = exc.code
        else:
            raise AssertionError("expected HTTPError")
    finally:
        server.close()

    assert status == 503
