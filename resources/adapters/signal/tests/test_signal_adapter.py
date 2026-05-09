"""Behavior tests for the Signal websocket adapter."""

from __future__ import annotations

import json

import pytest

from lib.shared.inbound_adapter import InboundCallbackResult
from resources.adapters.signal.adapter import (
    SignalAdapterDependencyError,
)
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

    def post(self, url: str, **kwargs):
        if self.raise_send is not None:
            raise self.raise_send
        self.posts.append((url, kwargs.get("json")))
        return _FakeHttpResponse(self.response_payload)


def _adapter() -> SignalRestApiAdapter:
    adapter = SignalRestApiAdapter(
        settings=SignalAdapterSettings(
            receive_e164="+13333333333",
            receive_connect_timeout_seconds=2.0,
            receive_heartbeat_seconds=5.0,
            failure_backoff_initial_seconds=1.0,
            failure_backoff_max_seconds=8.0,
            failure_backoff_multiplier=2.0,
            failure_backoff_jitter_ratio=0.0,
        )
    )
    adapter._signal_client = _FakeSignalClient()  # type: ignore[attr-defined]
    adapter._ensure_worker_started_locked = lambda: None  # type: ignore[method-assign]
    return adapter


def test_process_receive_payload_invokes_callback_and_sends_receipt() -> None:
    """Accepted queued messages should invoke the callback and send a read receipt."""
    adapter = _adapter()
    signal = adapter._signal_client
    callback_calls: list[str] = []
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
    adapter._process_receive_payload(
        registration=registration,
        raw_payload_json=json.dumps(
            {
                "account": "+12025550100",
                "envelope": {
                    "source": "+12025550100",
                    "sourceDevice": 1,
                    "timestamp": 1730000000000,
                    "dataMessage": {"message": "hello"},
                },
            }
        ),
    )

    assert callback_calls == ["hello"]
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


def test_process_receive_payload_retries_pending_payload_after_callback_failure() -> (
    None
):
    """Dependency failures should leave the wrapped payload queued for retry."""
    adapter = _adapter()
    attempts = 0

    def _callback(*, meta, message) -> InboundCallbackResult:
        del meta
        del message
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise SignalAdapterDependencyError("connect failed")
        return InboundCallbackResult(
            accepted=True,
            queued=True,
            reason="accepted",
            sender_e164="+12025550100",
            timestamp_ms=1,
        )

    adapter.register_callback(callback=_callback)
    registration = adapter._get_registration()
    assert registration is not None

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
    assert len(adapter._pending_payloads) == 1

    adapter._flush_pending(registration=registration)
    assert len(adapter._pending_payloads) == 0


def test_process_receive_payload_does_not_send_receipt_when_not_queued() -> None:
    """Rejected or ignored callbacks should not trigger a read receipt."""
    adapter = _adapter()
    signal = adapter._signal_client
    adapter.register_callback(
        callback=lambda *, meta, message: InboundCallbackResult(  # noqa: ARG005
            accepted=False,
            queued=False,
            reason=f"ignored:{message.message_text}",
        )
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
                    "timestamp": 1,
                    "dataMessage": {"message": "hello"},
                },
            }
        ),
    )

    assert signal.posts == []


def test_decode_receive_payload_accepts_dict_and_list_shapes() -> None:
    """Receive payload decoding should support both object and list websocket frames."""
    adapter = _adapter()

    assert adapter._decode_receive_payload('{"account":"+1"}') == [{"account": "+1"}]
    assert adapter._decode_receive_payload('[{"account":"+1"},{"account":"+2"}]') == [
        {"account": "+1"},
        {"account": "+2"},
    ]


def test_build_receive_websocket_url_uses_ws_scheme() -> None:
    """HTTP base URLs should map to websocket receive URLs."""
    adapter = _adapter()

    assert adapter._build_receive_websocket_url() == (
        "ws://signal-api:8080/v1/receive/%2B13333333333"
    )


def test_settings_require_heartbeat_to_exceed_connect_timeout() -> None:
    """Signal adapter config should fail fast on invalid websocket timing."""
    with pytest.raises(ValueError, match="receive_heartbeat_seconds"):
        SignalAdapterSettings(
            receive_e164="+13333333333",
            receive_connect_timeout_seconds=10.0,
            receive_heartbeat_seconds=10.0,
        )


def test_health_reports_local_readiness_without_provider_probe() -> None:
    """Adapter readiness should not depend on provider health reachability."""
    adapter = _adapter()

    class _BrokenSignalClient:
        def get(self, _url: str, **_kwargs):
            raise AssertionError("provider health should not be probed")

        def post(self, _url: str, **_kwargs):
            raise AssertionError("unexpected post")

    adapter._signal_client = _BrokenSignalClient()  # type: ignore[attr-defined]

    result = adapter.health()

    assert result.adapter_ready is True
    assert result.detail == "ready; callback=unconfigured; receive_loop=stopped"


def test_mint_slash_authenticity_proof_uses_on_disk_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Adapter mints a proof that verifies under the freshly-written secret."""
    from lib.shared.auth.slash_authenticity import (
        generate_and_write_secret,
        verify_proof,
    )

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    secret = generate_and_write_secret(tmp_path / "brain" / "slash_authenticity_secret")

    adapter = _adapter()
    proof = adapter.mint_slash_authenticity_proof(
        channel="signal",
        message_text="/workspace-register --path /tmp/foo",
    )

    import time as _time

    assert verify_proof(
        secret,
        channel="signal",
        message_text="/workspace-register --path /tmp/foo",
        proof=proof,
        now_ms=int(_time.time() * 1000),
        validity_seconds=60,
    )


def test_mint_slash_authenticity_proof_raises_when_secret_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Adapter surfaces a dependency error when the secret file is absent."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

    adapter = _adapter()
    with pytest.raises(SignalAdapterDependencyError):
        adapter.mint_slash_authenticity_proof(
            channel="signal",
            message_text="/anything",
        )
