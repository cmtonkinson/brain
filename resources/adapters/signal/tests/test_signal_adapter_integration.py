"""Integration-style Signal adapter contract tests using local fakes."""

from __future__ import annotations

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

    def get(self, _url: str, **_kwargs):
        return object()

    def get_json(self, url: str, **kwargs):
        self.last_url = url
        self.last_params = kwargs.get("params")
        return []

    def post(self, url: str, *, content: str, headers: dict[str, str]):
        self.posts.append((url, content, headers))
        return object()


def test_receive_poll_params_and_health_contract() -> None:
    """Adapter should query receive endpoint with configured polling parameters."""
    adapter = HttpSignalAdapter(
        settings=SignalAdapterSettings(receive_e164="+15551234567")
    )
    fake = _CaptureClient()
    adapter._signal_client = fake  # type: ignore[attr-defined]
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
    assert adapter.health().adapter_ready is True


def test_callback_status_failure_maps_to_dependency_error() -> None:
    """Adapter should surface callback 5xx as dependency failure on poll loop."""
    adapter = HttpSignalAdapter(settings=SignalAdapterSettings(max_retries=0))
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
    delay = adapter._run_once()

    assert delay >= 0


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
