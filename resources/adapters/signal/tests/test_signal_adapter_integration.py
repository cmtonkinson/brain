"""Integration-style Signal adapter contract tests using local fakes."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from packages.brain_shared.http import HttpStatusError
from resources.adapters.signal.config import SignalAdapterSettings
from resources.adapters.signal.signal_adapter import SignalAdapterDependencyError
from resources.adapters.signal.signal_adapter import SignalRestApiAdapter


class _CaptureClient:
    """Minimal HTTP client fake capturing outbound request shapes."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, str, dict[str, str]]] = []
        self.signal_posts: list[tuple[str, object]] = []

    def get(self, _url: str, **_kwargs):
        return object()

    def post(self, url: str, **kwargs):
        if "content" in kwargs and "headers" in kwargs:
            self.posts.append((url, kwargs["content"], kwargs["headers"]))
            return object()
        self.signal_posts.append((url, kwargs.get("json")))
        return object()

    def request_json(self, method: str, url: str, **kwargs):
        assert method == "POST"
        self.post(url, **kwargs)
        return {
            "ok": True,
            "accepted": True,
            "queued": True,
            "reason": "accepted",
            "message": {
                "sender_e164": "+12025550100",
                "timestamp_ms": 1730000000000,
            },
        }


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
    payload = """
        {"account":"+15551234567","envelope":{"source":"+12025550100","timestamp":1730000000000,"dataMessage":{"message":"hello"}}}
    """.strip()
    session = _FakeClientSession(adapter=adapter, payload=payload)
    original_client_session = aiohttp.ClientSession

    def _fake_client_session(*args, **kwargs):
        del args
        return session

    aiohttp.ClientSession = _fake_client_session  # type: ignore[assignment]
    adapter._signal_client = fake  # type: ignore[attr-defined]
    adapter._callback_client = fake  # type: ignore[attr-defined]
    adapter._ensure_worker_started_locked = lambda: None  # type: ignore[method-assign]
    try:
        adapter.register_webhook(
            callback_url="http://localhost/webhook",
            shared_secret="secret",
        )
        registration = adapter._get_registration()
        assert registration is not None
        asyncio.run(adapter._run_receive_session(registration=registration))
    finally:
        aiohttp.ClientSession = original_client_session  # type: ignore[assignment]
        adapter._stop_event.clear()  # type: ignore[attr-defined]

    assert session.last_url == "ws://signal-api:8080/v1/receive/%2B15551234567"
    assert session.last_heartbeat == 30.0
    assert fake.posts[0][0] == "http://localhost/webhook"
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


def test_settings_require_heartbeat_to_exceed_connect_timeout() -> None:
    """Signal adapter config should fail fast on invalid websocket timing."""
    with pytest.raises(ValueError, match="receive_heartbeat_seconds"):
        SignalAdapterSettings(
            receive_connect_timeout_seconds=10.0,
            receive_heartbeat_seconds=10.0,
        )


def test_callback_status_failure_maps_to_dependency_error() -> None:
    """Adapter should surface callback 5xx as dependency failure on poll loop."""
    adapter = SignalRestApiAdapter(settings=SignalAdapterSettings(max_retries=0))
    fake = _CaptureClient()

    def _raise_post(*_args, **_kwargs):
        raise HttpStatusError(message="err", method="POST", url="u", status_code=503)

    fake.post = _raise_post  # type: ignore[method-assign]
    adapter._signal_client = fake  # type: ignore[attr-defined]
    adapter._callback_client = fake  # type: ignore[attr-defined]
    adapter._ensure_worker_started_locked = lambda: None  # type: ignore[method-assign]

    adapter.register_webhook(
        callback_url="http://localhost/webhook",
        shared_secret="secret",
    )
    adapter._pending_webhooks.append('{"data": {"message": "x"}}')  # type: ignore[attr-defined]
    registration = adapter._get_registration()
    assert registration is not None
    delay = 0.0
    with pytest.raises(SignalAdapterDependencyError, match="status 503"):
        adapter._flush_pending(registration=registration)

    assert delay >= 0


def test_receive_websocket_handshake_failure_maps_to_dependency_error() -> None:
    """Adapter should surface websocket handshake failures as dependency errors."""
    adapter = SignalRestApiAdapter(settings=SignalAdapterSettings())
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
        adapter.register_webhook(
            callback_url="http://localhost/webhook",
            shared_secret="secret",
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
    adapter = SignalRestApiAdapter(settings=SignalAdapterSettings())
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
