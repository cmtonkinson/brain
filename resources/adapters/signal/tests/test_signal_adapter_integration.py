"""Integration-style Signal adapter contract tests using local fakes."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from lib.shared.http import HttpStatusError
from lib.shared.inbound_adapter import InboundCallbackResult
from lib.shared.inbound_message import InboundMessage
from resources.adapters.signal.adapter import (
    SignalAdapterDependencyError,
)
from resources.adapters.signal.config import SignalAdapterSettings
from resources.adapters.signal.signal_adapter import SignalRestApiAdapter


class _CaptureClient:
    """Minimal HTTP client fake capturing outbound request shapes."""

    def __init__(self) -> None:
        self.signal_posts: list[tuple[str, object]] = []

    def get(self, _url: str, **_kwargs):
        return object()

    def post(self, url: str, **kwargs):
        self.signal_posts.append((url, kwargs.get("json")))
        return object()


class _FakeWebsocketMessage:
    def __init__(self, *, message_type: aiohttp.WSMsgType, data: str | None):
        self.type = message_type
        self.data = data


class _FakeWebsocket:
    def __init__(self, *, adapter: SignalRestApiAdapter, payload: str) -> None:
        self._adapter = adapter
        self._payload = payload
        self._delivered = False

    async def __aenter__(self) -> "_FakeWebsocket":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb

    async def receive(self) -> _FakeWebsocketMessage:
        if not self._delivered:
            self._delivered = True
            self._adapter._stop_event.set()  # type: ignore[attr-defined]
            return _FakeWebsocketMessage(
                message_type=aiohttp.WSMsgType.TEXT,
                data=self._payload,
            )
        return _FakeWebsocketMessage(
            message_type=aiohttp.WSMsgType.CLOSED,
            data=None,
        )

    def exception(self) -> Exception | None:
        return None


class _FakeClientSession:
    def __init__(
        self, *, adapter: SignalRestApiAdapter, payload: str, **_kwargs
    ) -> None:
        self._adapter = adapter
        self._payload = payload
        self.last_url: str | None = None
        self.last_heartbeat: float | None = None

    async def __aenter__(self) -> "_FakeClientSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb

    def ws_connect(self, url: str, *, heartbeat: float, autoping: bool):
        del autoping
        self.last_url = url
        self.last_heartbeat = heartbeat
        return _FakeWebsocket(adapter=self._adapter, payload=self._payload)


def test_receive_websocket_url_and_health_contract() -> None:
    """Adapter should connect to the websocket receive endpoint."""
    adapter = SignalRestApiAdapter(
        settings=SignalAdapterSettings(receive_e164="+15551234567")
    )
    fake = _CaptureClient()
    callback_calls: list[str] = []
    payload = """
        {"account":"+15551234567","envelope":{"source":"+12025550100","timestamp":1730000000000,"dataMessage":{"message":"hello"}}}
    """.strip()
    session = _FakeClientSession(adapter=adapter, payload=payload)
    original_client_session = aiohttp.ClientSession

    def _fake_client_session(*args, **kwargs):
        del args, kwargs
        return session

    aiohttp.ClientSession = _fake_client_session  # type: ignore[assignment]
    adapter._signal_client = fake  # type: ignore[attr-defined]
    adapter._ensure_worker_started_locked = lambda: None  # type: ignore[method-assign]
    try:
        adapter.register_callback(
            callback=lambda *, meta, message: (  # noqa: ARG005
                callback_calls.append(message.message_text)
                or InboundCallbackResult(
                    accepted=True,
                    queued=True,
                    reason="accepted",
                    sender_e164="+12025550100",
                    timestamp_ms=1730000000000,
                )
            )
        )
        registration = adapter._get_registration()
        assert registration is not None
        asyncio.run(adapter._run_receive_session(registration=registration))
    finally:
        aiohttp.ClientSession = original_client_session  # type: ignore[assignment]
        adapter._stop_event.clear()  # type: ignore[attr-defined]

    assert session.last_url == "ws://signal-api:8080/v1/receive/%2B15551234567"
    assert session.last_heartbeat == 30.0
    assert len(callback_calls) == 1
    assert fake.signal_posts == [
        (
            "/v1/receipts/%2B15551234567",
            {
                "receipt_type": "read",
                "recipient": "+12025550100",
                "timestamp": 1730000000000,
            },
        )
    ]
    assert adapter.health().adapter_ready is True


def test_callback_failure_maps_to_dependency_error() -> None:
    """Callback dependency failures should surface from pending flush."""
    adapter = SignalRestApiAdapter(
        settings=SignalAdapterSettings(receive_e164="+13333333333", max_retries=0)
    )
    fake = _CaptureClient()
    adapter._signal_client = fake  # type: ignore[attr-defined]
    adapter._ensure_worker_started_locked = lambda: None  # type: ignore[method-assign]

    def _callback(*, meta, message: InboundMessage) -> InboundCallbackResult:
        del meta
        del message
        raise SignalAdapterDependencyError("status 503")

    adapter.register_callback(callback=_callback)
    adapter._pending_payloads.append(
        InboundMessage(channel="signal", message_text="x", timestamp_ms=1)
    )  # type: ignore[attr-defined]
    registration = adapter._get_registration()
    assert registration is not None

    with pytest.raises(SignalAdapterDependencyError, match="status 503"):
        adapter._flush_pending(registration=registration)


def test_receive_websocket_handshake_failure_maps_to_dependency_error() -> None:
    """Adapter should surface websocket handshake failures as dependency errors."""
    adapter = SignalRestApiAdapter(
        settings=SignalAdapterSettings(receive_e164="+13333333333")
    )
    adapter._ensure_worker_started_locked = lambda: None  # type: ignore[method-assign]
    original_client_session = aiohttp.ClientSession

    class _HandshakeErrorSession:
        async def __aenter__(self) -> "_HandshakeErrorSession":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

        def ws_connect(self, *_args, **_kwargs):
            raise aiohttp.WSServerHandshakeError(
                request_info=None,
                history=(),
                status=400,
                message="bad request",
                headers=None,
            )

    aiohttp.ClientSession = lambda *args, **kwargs: _HandshakeErrorSession()  # type: ignore[assignment]
    try:
        adapter.register_callback(
            callback=lambda *, meta, message: InboundCallbackResult(  # noqa: ARG005
                accepted=True,
                queued=True,
                reason=message.message_text,
            )
        )
        registration = adapter._get_registration()
        assert registration is not None
        with pytest.raises(
            SignalAdapterDependencyError,
            match="handshake failed with status 400",
        ):
            asyncio.run(adapter._run_receive_session(registration=registration))
    finally:
        aiohttp.ClientSession = original_client_session  # type: ignore[assignment]


def test_send_message_maps_transport_status_errors_to_dependency() -> None:
    """Outbound send should map HTTP status failures into dependency errors."""
    adapter = SignalRestApiAdapter(
        settings=SignalAdapterSettings(receive_e164="+13333333333")
    )
    fake = _CaptureClient()

    def _raise_post(*_args, **_kwargs):
        raise HttpStatusError(
            message="err",
            method="POST",
            url="http://signal-api:8080/v2/send",
            status_code=503,
        )

    fake.post = _raise_post  # type: ignore[method-assign]
    adapter._signal_client = fake  # type: ignore[attr-defined]

    try:
        adapter.send_message(
            sender_e164="+12025550101",
            recipient_e164="+12025550100",
            message="hello",
        )
    except SignalAdapterDependencyError as exc:
        assert "status 503" in str(exc)
    else:
        raise AssertionError("expected SignalAdapterDependencyError")
