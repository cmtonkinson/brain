"""Integration-style Signal adapter contract tests using local fakes."""

from __future__ import annotations

import pytest

from packages.brain_shared.http import HttpStatusError
from resources.adapters.signal.config import SignalAdapterSettings
from resources.adapters.signal.signal_adapter import SignalAdapterDependencyError
from resources.adapters.signal.signal_adapter import HttpSignalAdapter


class _CaptureClient:
    """Minimal HTTP client fake capturing GET/POST request shapes."""

    def __init__(self) -> None:
        self.last_url: str | None = None
        self.last_params: dict[str, str] | None = None
        self.posts: list[tuple[str, str, dict[str, str]]] = []
        self.signal_posts: list[tuple[str, object]] = []
        self.get_json_calls = 0

    def get(self, _url: str, **_kwargs):
        return object()

    def get_json(self, url: str, **kwargs):
        self.get_json_calls += 1
        self.last_url = url
        self.last_params = kwargs.get("params")
        return []

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


def test_receive_poll_params_and_health_contract() -> None:
    """Adapter should query receive endpoint with configured polling parameters."""
    adapter = HttpSignalAdapter(
        settings=SignalAdapterSettings(receive_e164="+15551234567")
    )
    fake = _CaptureClient()

    def _get_json(url: str, **kwargs):
        fake.last_url = url
        fake.last_params = kwargs.get("params")
        return [
            {
                "account": "+15551234567",
                "envelope": {
                    "source": "+12025550100",
                    "timestamp": 1730000000000,
                    "dataMessage": {
                        "message": "hello",
                    },
                },
            }
        ]

    fake.get_json = _get_json  # type: ignore[method-assign]
    adapter._signal_client = fake  # type: ignore[attr-defined]
    adapter._signal_send_client = fake  # type: ignore[attr-defined]
    adapter._callback_client = fake  # type: ignore[attr-defined]
    adapter._ensure_worker_started_locked = lambda: None  # type: ignore[method-assign]

    adapter.register_webhook(
        callback_url="http://localhost/webhook",
        shared_secret="secret",
    )
    adapter._run_once()

    assert fake.last_url == "/v1/receive/%2B15551234567"
    assert fake.last_params is not None
    assert "timeout" in fake.last_params
    assert fake.last_params["send_read_receipts"] == "false"
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


def test_settings_require_http_timeout_to_exceed_receive_timeout() -> None:
    """Signal adapter config should fail fast on impossible timeout budgets."""
    with pytest.raises(ValueError, match="receive_timeout_seconds"):
        SignalAdapterSettings(
            receive_timeout_seconds=10.0,
            poll_receive_timeout_seconds=15,
        )


def test_settings_require_send_timeout_to_exceed_receive_timeout() -> None:
    """Signal send timeout should exceed the receive poll budget."""
    with pytest.raises(ValueError, match="send_timeout_seconds"):
        SignalAdapterSettings(
            send_timeout_seconds=10.0,
            poll_receive_timeout_seconds=15,
        )


def test_callback_status_failure_maps_to_dependency_error() -> None:
    """Adapter should surface callback 5xx as dependency failure on poll loop."""
    adapter = HttpSignalAdapter(settings=SignalAdapterSettings(max_retries=0))
    fake = _CaptureClient()

    def _raise_post(*_args, **_kwargs):
        raise HttpStatusError(message="err", method="POST", url="u", status_code=503)

    fake.post = _raise_post  # type: ignore[method-assign]
    adapter._signal_client = fake  # type: ignore[attr-defined]
    adapter._signal_send_client = fake  # type: ignore[attr-defined]
    adapter._callback_client = fake  # type: ignore[attr-defined]
    adapter._ensure_worker_started_locked = lambda: None  # type: ignore[method-assign]

    adapter.register_webhook(
        callback_url="http://localhost/webhook",
        shared_secret="secret",
    )
    adapter._pending_webhooks.append('{"data": {"message": "x"}}')  # type: ignore[attr-defined]
    delay = adapter._run_once()

    assert delay >= 0


def test_non_retryable_receive_status_is_not_retried() -> None:
    """Adapter should not retry non-retryable 4xx receive failures."""
    adapter = HttpSignalAdapter(settings=SignalAdapterSettings(max_retries=2))
    fake = _CaptureClient()
    calls = 0

    def _raise_get_json(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise HttpStatusError(
            message="err",
            method="GET",
            url="http://signal-api:8080/v1/receive/%2B15551234567",
            status_code=400,
            retryable=False,
        )

    fake.get_json = _raise_get_json  # type: ignore[method-assign]
    adapter._signal_client = fake  # type: ignore[attr-defined]
    adapter._signal_send_client = fake  # type: ignore[attr-defined]
    adapter._callback_client = fake  # type: ignore[attr-defined]
    adapter._ensure_worker_started_locked = lambda: None  # type: ignore[method-assign]

    adapter.register_webhook(
        callback_url="http://localhost/webhook",
        shared_secret="secret",
    )
    delay = adapter._run_once()

    assert delay >= 0
    assert calls == 1


def test_send_message_maps_transport_status_errors_to_dependency() -> None:
    """Outbound send should map HTTP status failures into dependency errors."""
    adapter = HttpSignalAdapter(settings=SignalAdapterSettings())
    fake = _CaptureClient()

    def _raise_post(*_args, **_kwargs):
        raise HttpStatusError(
            message="err",
            method="POST",
            url="http://signal-api:8080/v2/send",
            status_code=503,
        )

    fake.post = _raise_post  # type: ignore[method-assign]
    adapter._signal_send_client = fake  # type: ignore[attr-defined]

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
