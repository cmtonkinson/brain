"""Behavior tests for the Signal websocket adapter."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import aiohttp
import pytest

from packages.brain_shared.http import HttpRequestError
from resources.adapters.signal.adapter import SignalAdapterDependencyError
from resources.adapters.signal import signal_adapter as signal_adapter_module
from resources.adapters.signal.config import SignalAdapterSettings
from resources.adapters.signal.signal_adapter import SignalRestApiAdapter


class _FakeHttpResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _FakeSignalClient:
    def __init__(self) -> None:
        self.raise_send: Exception | None = None
        self.posts: list[tuple[str, object]] = []
        self.response_payload: object = {}

    def get(self, _url: str, **_kwargs):
        return object()

    def post(self, url: str, **kwargs):
        if self.raise_send is not None:
            raise self.raise_send
        self.posts.append((url, kwargs.get("json")))
        return _FakeHttpResponse(self.response_payload)


class _FakeCallbackClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, str, dict[str, str]]] = []
        self.raise_post: Exception | None = None
        self.response_payload: object = {
            "ok": True,
            "accepted": True,
            "queued": True,
            "reason": "accepted",
            "message": {
                "sender_e164": "+12025550100",
                "timestamp_ms": 1730000000000,
            },
        }

    def request_json(
        self,
        _method: str,
        url: str,
        *,
        content: str,
        headers: dict[str, str],
    ):
        if self.raise_post is not None:
            raise self.raise_post
        self.posts.append((url, content, headers))
        return self.response_payload


class _FakeWebsocketMessage:
    def __init__(self, *, message_type: aiohttp.WSMsgType, data: str | bytes | None):
        self.type = message_type
        self.data = data


class _FakeWebsocket:
    def __init__(self, *, adapter: SignalRestApiAdapter, payloads: list[str]) -> None:
        self._adapter = adapter
        self._payloads = list(payloads)
        self._receive_calls = 0

    async def __aenter__(self) -> "_FakeWebsocket":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb

    async def receive(self) -> _FakeWebsocketMessage:
        if self._payloads:
            self._receive_calls += 1
            payload = self._payloads.pop(0)
            self._adapter._stop_event.set()  # type: ignore[attr-defined]
            return _FakeWebsocketMessage(
                message_type=aiohttp.WSMsgType.TEXT,
                data=payload,
            )
        return _FakeWebsocketMessage(
            message_type=aiohttp.WSMsgType.CLOSED,
            data=None,
        )

    def exception(self) -> Exception | None:
        return None


class _FakeClientSession:
    last_connect_url: str | None = None
    last_heartbeat: float | None = None

    def __init__(
        self, *, adapter: SignalRestApiAdapter, payloads: list[str], **_kwargs
    ):
        self._adapter = adapter
        self._payloads = payloads

    async def __aenter__(self) -> "_FakeClientSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb

    def ws_connect(self, url: str, *, heartbeat: float, autoping: bool):
        del autoping
        type(self).last_connect_url = url
        type(self).last_heartbeat = heartbeat
        return _FakeWebsocket(adapter=self._adapter, payloads=self._payloads)


def _adapter() -> SignalRestApiAdapter:
    adapter = SignalRestApiAdapter(
        settings=SignalAdapterSettings(
            receive_connect_timeout_seconds=2.0,
            receive_heartbeat_seconds=5.0,
            failure_backoff_initial_seconds=1.0,
            failure_backoff_max_seconds=8.0,
            failure_backoff_multiplier=2.0,
            failure_backoff_jitter_ratio=0.0,
        )
    )
    adapter._signal_client = _FakeSignalClient()  # type: ignore[attr-defined]
    adapter._callback_client = _FakeCallbackClient()  # type: ignore[attr-defined]
    adapter._ensure_worker_started_locked = lambda: None  # type: ignore[method-assign]
    return adapter


def test_process_receive_payload_forwards_signed_webhook_and_receipt() -> None:
    adapter = _adapter()
    signal = adapter._signal_client
    callback = adapter._callback_client
    adapter.register_webhook(
        callback_url="http://switchboard:8091/v1/inbound/signal/webhook",
        shared_secret="secret",
    )

    registration = adapter._get_registration()
    assert registration is not None
    adapter._process_receive_payload(
        registration=registration,
        raw_payload_json=json.dumps(
            {
                "account": "+12025550100",
                "envelope": {
                    "source": "+12025550100",
                    "sourceDevice": 1,
                    "timestamp": 1730000000000,
                    "dataMessage": {
                        "message": "hello",
                    },
                },
            }
        ),
    )

    assert len(callback.posts) == 1
    url, body, headers = callback.posts[0]
    payload = json.loads(body)
    assert url == "http://switchboard:8091/v1/inbound/signal/webhook"
    assert payload["data"]["envelope"]["dataMessage"]["message"] == "hello"
    assert headers["X-Brain-Signature"].startswith("sha256=")
    assert headers["X-Brain-Timestamp"].isdigit()
    assert signal.posts == [
        (
            "/v1/receipts/%2B13333333333",
            {
                "receipt_type": "read",
                "recipient": "+12025550100",
                "timestamp": 1730000000000,
            },
        )
    ]


def test_process_receive_payload_retries_pending_webhook_after_callback_failure() -> (
    None
):
    adapter = _adapter()
    signal = adapter._signal_client
    callback = adapter._callback_client
    adapter.register_webhook(
        callback_url="http://switchboard:8091/v1/inbound/signal/webhook",
        shared_secret="secret",
    )
    registration = adapter._get_registration()
    assert registration is not None

    callback.raise_post = HttpRequestError(
        message="connect failed",
        method="POST",
        url="http://switchboard:8091/v1/inbound/signal/webhook",
        retryable=True,
    )
    with pytest.raises(SignalAdapterDependencyError, match="connect failed"):
        adapter._process_receive_payload(
            registration=registration,
            raw_payload_json=json.dumps(
                {
                    "account": "+12025550100",
                    "envelope": {
                        "source": "+12025550100",
                        "timestamp": 1,
                        "dataMessage": {"message": "hello"},
                    },
                }
            ),
        )
    assert len(adapter._pending_webhooks) == 1

    callback.raise_post = None
    adapter._flush_pending(registration=registration)
    assert len(callback.posts) == 1
    assert len(adapter._pending_webhooks) == 0
    assert len(signal.posts) == 1


def test_process_receive_payload_does_not_send_read_receipt_when_not_queued() -> None:
    adapter = _adapter()
    signal = adapter._signal_client
    callback = adapter._callback_client
    callback.response_payload = {
        "ok": True,
        "accepted": False,
        "queued": False,
        "reason": "signal exception event: UntrustedIdentityException",
    }
    adapter.register_webhook(
        callback_url="http://switchboard:8091/v1/inbound/signal/webhook",
        shared_secret="secret",
    )
    registration = adapter._get_registration()
    assert registration is not None

    adapter._process_receive_payload(
        registration=registration,
        raw_payload_json=json.dumps(
            {
                "account": "+12025550100",
                "exception": {
                    "type": "UntrustedIdentityException",
                    "message": "Untrusted identity",
                },
                "envelope": {
                    "source": "+12025550100",
                    "timestamp": 1730000000000,
                },
            }
        ),
    )

    assert len(callback.posts) == 1
    assert signal.posts == []


def test_run_loop_once_applies_exponential_backoff_on_receive_failure() -> None:
    adapter = _adapter()
    adapter.register_webhook(
        callback_url="http://switchboard:8091/v1/inbound/signal/webhook",
        shared_secret="secret",
    )

    async def _raise_receive(*, registration) -> None:
        del registration
        raise SignalAdapterDependencyError("signal receive websocket closed")

    adapter._run_receive_session = _raise_receive  # type: ignore[method-assign]

    assert adapter._run_loop_once() == 1.0
    assert adapter._run_loop_once() == 2.0
    assert adapter._run_loop_once() == 4.0
    assert adapter._run_loop_once() == 8.0
    assert adapter._run_loop_once() == 8.0


def test_run_receive_session_connects_to_receive_websocket_and_forwards() -> None:
    adapter = _adapter()
    signal = adapter._signal_client
    callback = adapter._callback_client
    adapter.register_webhook(
        callback_url="http://switchboard:8091/v1/inbound/signal/webhook",
        shared_secret="secret",
    )
    registration = adapter._get_registration()
    assert registration is not None

    payload = json.dumps(
        {
            "account": "+12025550100",
            "envelope": {
                "source": "+12025550100",
                "timestamp": 1730000000000,
                "dataMessage": {"message": "hello"},
            },
        }
    )
    original_client_session = aiohttp.ClientSession

    def _fake_client_session(*args, **kwargs):
        del args
        return _FakeClientSession(adapter=adapter, payloads=[payload], **kwargs)

    aiohttp.ClientSession = _fake_client_session  # type: ignore[assignment]
    try:
        asyncio.run(adapter._run_receive_session(registration=registration))
    finally:
        aiohttp.ClientSession = original_client_session  # type: ignore[assignment]
        adapter._stop_event.clear()  # type: ignore[attr-defined]

    assert (
        _FakeClientSession.last_connect_url
        == "ws://signal-api:8080/v1/receive/%2B13333333333"
    )
    assert _FakeClientSession.last_heartbeat == 5.0
    assert len(callback.posts) == 1
    assert len(signal.posts) == 1


def test_send_message_posts_expected_payload() -> None:
    adapter = _adapter()
    signal = adapter._signal_client

    result = adapter.send_message(
        sender_e164="+12025550101",
        recipient_e164="+12025550100",
        message="hello",
    )

    assert result.delivered is True
    assert len(signal.posts) == 1
    url, payload = signal.posts[0]
    assert url == "/v2/send"
    assert payload == {
        "message": "hello",
        "text_mode": "styled",
        "number": "+12025550101",
        "recipients": ["+12025550100"],
    }


def test_send_message_extracts_timestamp_and_emits_verbose_log() -> None:
    adapter = _adapter()
    signal = adapter._signal_client
    signal.response_payload = {"timestamp": 1730000000123}

    with patch.object(signal_adapter_module._LOGGER, "verbose") as verbose_log:
        result = adapter.send_message(
            sender_e164="+12025550101",
            recipient_e164="+12025550100",
            message="hello",
        )

    assert result.sent_timestamp_ms == 1730000000123
    verbose_log.assert_called_once()
    assert verbose_log.call_args.args == (
        "signal adapter send_message response captured",
    )
    assert verbose_log.call_args.kwargs["extra"]["sent_timestamp_ms"] == 1730000000123


def test_process_receive_payload_emits_verbose_raw_boundary_logs() -> None:
    adapter = _adapter()
    callback = adapter._callback_client
    adapter.register_webhook(
        callback_url="http://switchboard:8091/v1/inbound/signal/webhook",
        shared_secret="secret",
    )
    registration = adapter._get_registration()
    assert registration is not None

    raw_payload_json = json.dumps(
        {
            "account": "+12025550100",
            "envelope": {
                "source": "+12025550100",
                "timestamp": 1730000000000,
                "dataMessage": {
                    "message": "approved",
                    "quote": {"timestamp": 1730000000999},
                    "reaction": {"emoji": "👍", "targetSentTimestamp": 1730000000888},
                },
            },
        }
    )

    with patch.object(signal_adapter_module._LOGGER, "verbose") as verbose_log:
        adapter._process_receive_payload(
            registration=registration,
            raw_payload_json=raw_payload_json,
        )

    assert len(callback.posts) == 1
    assert verbose_log.call_count == 2
    assert verbose_log.call_args_list[0].args == (
        "signal adapter received websocket payload",
    )
    assert verbose_log.call_args_list[0].kwargs["extra"]["contains_quote"] is True
    assert verbose_log.call_args_list[0].kwargs["extra"]["contains_reaction"] is True
    assert verbose_log.call_args_list[1].args == (
        "signal adapter queued callback payload",
    )
    assert verbose_log.call_args_list[1].kwargs["extra"]["raw_body_json"].strip() != ""
