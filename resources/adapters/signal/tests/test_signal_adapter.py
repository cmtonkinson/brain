"""Behavior tests for Signal polling adapter."""

from __future__ import annotations

import json

from packages.brain_shared.http import HttpRequestError, HttpStatusError
from resources.adapters.signal.config import SignalAdapterSettings
from resources.adapters.signal.signal_adapter import HttpSignalAdapter


class _FakeSignalClient:
    def __init__(self) -> None:
        self.receive_payload: object = []
        self.raise_receive: Exception | None = None
        self.raise_send: Exception | None = None
        self.posts: list[tuple[str, object]] = []

    def get(self, _url: str):
        return object()

    def get_json(self, _url: str, **_kwargs):
        if self.raise_receive is not None:
            raise self.raise_receive
        return self.receive_payload

    def post(self, url: str, **kwargs):
        if self.raise_send is not None:
            raise self.raise_send
        self.posts.append((url, kwargs.get("json")))
        return object()


class _FakeCallbackClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, str, dict[str, str]]] = []
        self.raise_post: Exception | None = None

    def post(self, url: str, *, content: str, headers: dict[str, str]):
        if self.raise_post is not None:
            raise self.raise_post
        self.posts.append((url, content, headers))
        return object()


def _adapter() -> HttpSignalAdapter:
    adapter = HttpSignalAdapter(
        settings=SignalAdapterSettings(
            poll_interval_seconds=0.1,
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


def test_run_once_polls_and_forwards_signed_webhook() -> None:
    adapter = _adapter()
    signal = adapter._signal_client
    callback = adapter._callback_client
    signal.receive_payload = [
        {
            "source": "+12025550100",
            "message": "hello",
            "timestamp": 1730000000000,
        }
    ]

    adapter.register_webhook(
        callback_url="http://switchboard:8091/v1/inbound/signal/webhook",
        shared_secret="secret",
        operator_e164="+12025550100",
    )

    delay = adapter._run_once()

    assert delay == 0.1
    assert len(callback.posts) == 1
    url, body, headers = callback.posts[0]
    payload = json.loads(body)
    assert url == "http://switchboard:8091/v1/inbound/signal/webhook"
    assert payload["data"]["message"] == "hello"
    assert headers["X-Brain-Signature"].startswith("sha256=")
    assert headers["X-Brain-Timestamp"].isdigit()


def test_run_once_retries_pending_webhook_after_callback_failure() -> None:
    adapter = _adapter()
    signal = adapter._signal_client
    callback = adapter._callback_client
    signal.receive_payload = [
        {"source": "+12025550100", "message": "hello", "timestamp": 1}
    ]

    adapter.register_webhook(
        callback_url="http://switchboard:8091/v1/inbound/signal/webhook",
        shared_secret="secret",
        operator_e164="+12025550100",
    )

    callback.raise_post = HttpRequestError(
        message="connect failed",
        method="POST",
        url="http://switchboard:8091/v1/inbound/signal/webhook",
        retryable=True,
    )
    first_delay = adapter._run_once()
    assert first_delay == 1.0
    assert len(adapter._pending_webhooks) == 1

    callback.raise_post = None
    second_delay = adapter._run_once()
    assert second_delay == 0.1
    assert len(callback.posts) == 1
    assert len(adapter._pending_webhooks) == 0


def test_run_once_applies_exponential_backoff_on_receive_failure() -> None:
    adapter = _adapter()
    signal = adapter._signal_client
    signal.raise_receive = HttpStatusError(
        message="bad request",
        method="GET",
        url="http://signal-api:8080/v1/receive/%2B12025550100",
        retryable=False,
        status_code=400,
    )

    adapter.register_webhook(
        callback_url="http://switchboard:8091/v1/inbound/signal/webhook",
        shared_secret="secret",
        operator_e164="+12025550100",
    )

    assert adapter._run_once() == 1.0
    assert adapter._run_once() == 2.0
    assert adapter._run_once() == 4.0
    assert adapter._run_once() == 8.0
    assert adapter._run_once() == 8.0


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
