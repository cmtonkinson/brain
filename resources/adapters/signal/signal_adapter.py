"""In-process Signal adapter implementation over signal-cli-rest-api."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections import deque
from dataclasses import dataclass
from random import random
from threading import Event, Lock, Thread
from time import time
from urllib.parse import quote, urlparse, urlunparse

import aiohttp

from packages.brain_shared.http import (
    HttpClient,
    HttpJsonDecodeError,
    HttpRequestError,
    HttpStatusError,
)
from packages.brain_shared.logging import get_logger, public_api_instrumented
from resources.adapters.signal.adapter import (
    SignalAdapter,
    SignalAdapterDependencyError,
    SignalAdapterHealthResult,
    SignalAdapterInternalError,
    SignalSendMessageResult,
    SignalWebhookRegistrationResult,
)
from resources.adapters.signal.component import RESOURCE_COMPONENT_ID
from resources.adapters.signal.config import SignalAdapterSettings
from resources.adapters.signal.constants import SIGNAL_HEALTH_PATH

_LOGGER = get_logger(__name__)
_HEADER_SIGNATURE = "X-Brain-Signature"
_HEADER_TIMESTAMP = "X-Brain-Timestamp"
_REGISTRATION_WAIT_SECONDS = 0.25
_RECEIVE_CHECK_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class _WebhookRegistration:
    callback_url: str
    shared_secret: str


@dataclass(frozen=True)
class _WebhookCallbackResult:
    accepted: bool
    queued: bool
    reason: str
    sender_e164: str
    timestamp_ms: int | None


class SignalRestApiAdapter(SignalAdapter):
    """Signal adapter backed by websocket receive and HTTP send/callback flows."""

    def __init__(self, *, settings: SignalAdapterSettings) -> None:
        self._settings = settings
        self._signal_client = HttpClient(
            base_url=settings.base_url.rstrip("/"),
            timeout_seconds=settings.send_timeout_seconds,
            headers={"Content-Type": "application/json"},
        )
        self._callback_client = HttpClient(
            timeout_seconds=settings.callback_timeout_seconds
        )
        self._lock = Lock()
        self._registration: _WebhookRegistration | None = None
        self._pending_webhooks: deque[str] = deque()
        self._worker: Thread | None = None
        self._stop_event = Event()
        self._backoff_seconds = settings.failure_backoff_initial_seconds

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def register_webhook(
        self,
        *,
        callback_url: str,
        shared_secret: str,
    ) -> SignalWebhookRegistrationResult:
        """Configure callback target and start receive loop when needed."""
        registration = _WebhookRegistration(
            callback_url=callback_url.strip(),
            shared_secret=shared_secret.strip(),
        )
        if registration.callback_url == "":
            raise SignalAdapterInternalError("callback_url must be non-empty")
        if registration.shared_secret == "":
            raise SignalAdapterInternalError("shared_secret must be non-empty")

        with self._lock:
            self._registration = registration
            self._ensure_worker_started_locked()

        return SignalWebhookRegistrationResult(
            registered=True,
            detail="configured; receive loop active",
        )

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def health(self) -> SignalAdapterHealthResult:
        """Return adapter health by probing Signal runtime health endpoint."""
        try:
            self._signal_client.get(
                SIGNAL_HEALTH_PATH,
                timeout=self._settings.health_timeout_seconds,
            )
        except (HttpRequestError, HttpStatusError, HttpJsonDecodeError) as exc:
            return SignalAdapterHealthResult(
                adapter_ready=False,
                detail=str(exc) or "signal runtime unavailable",
            )

        with self._lock:
            registration = self._registration
            worker_alive = self._worker is not None and self._worker.is_alive()
        callback_state = "configured" if registration is not None else "unconfigured"
        loop_state = "running" if worker_alive else "stopped"
        return SignalAdapterHealthResult(
            adapter_ready=True,
            detail=f"ok; callback={callback_state}; receive_loop={loop_state}",
        )

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def send_message(
        self,
        *,
        sender_e164: str,
        recipient_e164: str,
        message: str,
    ) -> SignalSendMessageResult:
        """Send one outbound Signal message via signal-cli-rest-api."""
        sender = sender_e164.strip()
        recipient = recipient_e164.strip()
        text = message.strip()
        if sender == "":
            raise SignalAdapterInternalError("sender_e164 must be non-empty")
        if recipient == "":
            raise SignalAdapterInternalError("recipient_e164 must be non-empty")
        if text == "":
            raise SignalAdapterInternalError("message must be non-empty")

        payload = {
            "message": text,
            "text_mode": "styled",
            "number": sender,
            "recipients": [recipient],
        }
        try:
            self._signal_client.post("/v2/send", json=payload)
        except HttpStatusError as exc:
            raise SignalAdapterDependencyError(
                f"signal send failed with status {exc.status_code}"
            ) from None
        except HttpRequestError as exc:
            raise SignalAdapterDependencyError(
                str(exc) or "signal send unavailable"
            ) from None

        return SignalSendMessageResult(
            delivered=True,
            recipient_e164=recipient,
            sender_e164=sender,
            detail="delivered",
        )

    def _run_loop(self) -> None:
        """Drive the receive websocket loop until shutdown."""
        while not self._stop_event.is_set():
            delay = self._run_loop_once()
            if delay > 0:
                self._stop_event.wait(delay)

    def _run_loop_once(self) -> float:
        """Run one receive-loop session and return the next delay."""
        registration = self._get_registration()
        if registration is None:
            return _REGISTRATION_WAIT_SECONDS

        for attempt in range(self._settings.max_retries + 1):
            try:
                asyncio.run(self._run_receive_session(registration=registration))
                self._backoff_seconds = self._settings.failure_backoff_initial_seconds
                return 0.0
            except SignalAdapterDependencyError as exc:
                if attempt < self._settings.max_retries:
                    continue
                _LOGGER.warning(
                    "signal adapter receive/forward dependency failure: %s",
                    str(exc),
                )
                return self._next_backoff_delay()
            except SignalAdapterInternalError as exc:
                if attempt < self._settings.max_retries:
                    continue
                _LOGGER.error(
                    "signal adapter receive/forward internal failure: %s",
                    str(exc),
                )
                return self._next_backoff_delay()
        return self._next_backoff_delay()

    def _ensure_worker_started_locked(self) -> None:
        """Start receive worker once when callback registration is configured."""
        if self._worker is not None:
            return
        self._stop_event.clear()
        self._worker = Thread(target=self._run_loop, daemon=True)
        self._worker.start()

    async def _run_receive_session(self, *, registration: _WebhookRegistration) -> None:
        """Open one receive websocket session and process frames until stopped."""
        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=self._settings.receive_connect_timeout_seconds,
            sock_connect=self._settings.receive_connect_timeout_seconds,
            sock_read=None,
        )
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.ws_connect(
                    self._build_receive_websocket_url(),
                    heartbeat=self._settings.receive_heartbeat_seconds,
                    autoping=True,
                ) as websocket:
                    self._backoff_seconds = (
                        self._settings.failure_backoff_initial_seconds
                    )
                    while not self._stop_event.is_set():
                        current_registration = self._get_registration()
                        if current_registration != registration:
                            return
                        await asyncio.to_thread(
                            self._flush_pending,
                            registration=current_registration,
                        )
                        if self._stop_event.is_set():
                            return
                        try:
                            message = await asyncio.wait_for(
                                websocket.receive(),
                                timeout=_RECEIVE_CHECK_INTERVAL_SECONDS,
                            )
                        except asyncio.TimeoutError:
                            continue
                        if message.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.CLOSING,
                        ):
                            raise SignalAdapterDependencyError(
                                "signal receive websocket closed"
                            )
                        if message.type == aiohttp.WSMsgType.ERROR:
                            detail = str(websocket.exception() or "").strip()
                            raise SignalAdapterDependencyError(
                                detail or "signal receive websocket error"
                            )
                        if message.type in (
                            aiohttp.WSMsgType.PING,
                            aiohttp.WSMsgType.PONG,
                        ):
                            continue
                        if message.type not in (
                            aiohttp.WSMsgType.TEXT,
                            aiohttp.WSMsgType.BINARY,
                        ):
                            continue
                        raw_payload = message.data
                        if isinstance(raw_payload, bytes):
                            raw_payload = raw_payload.decode("utf-8")
                        if not isinstance(raw_payload, str):
                            raise SignalAdapterInternalError(
                                "signal receive websocket payload must be text JSON"
                            )
                        await asyncio.to_thread(
                            self._process_receive_payload,
                            registration=current_registration,
                            raw_payload_json=raw_payload,
                        )
        except aiohttp.WSServerHandshakeError as exc:
            raise SignalAdapterDependencyError(
                f"signal receive websocket handshake failed with status {exc.status}"
            ) from None
        except aiohttp.ClientError as exc:
            raise SignalAdapterDependencyError(
                str(exc) or "signal receive unavailable"
            ) from None
        except asyncio.TimeoutError:
            raise SignalAdapterDependencyError("signal receive unavailable") from None

    def _process_receive_payload(
        self,
        *,
        registration: _WebhookRegistration,
        raw_payload_json: str,
    ) -> None:
        """Parse one websocket payload and forward its contained Signal items."""
        messages = self._decode_receive_payload(raw_payload_json)
        for message in messages:
            self._pending_webhooks.append(json.dumps({"data": message}))
        self._flush_pending(registration=registration)

    def _decode_receive_payload(self, raw_payload_json: str) -> list[dict[str, object]]:
        """Normalize one websocket payload into individual Signal items."""
        try:
            payload = json.loads(raw_payload_json)
        except json.JSONDecodeError as exc:
            raise SignalAdapterInternalError(
                f"signal receive websocket payload JSON invalid: {exc}"
            ) from None

        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            messages: list[dict[str, object]] = []
            for item in payload:
                if isinstance(item, dict):
                    messages.append(item)
            return messages
        raise SignalAdapterInternalError(
            "signal receive websocket payload must be a JSON object or array"
        )

    def _build_receive_websocket_url(self) -> str:
        """Build websocket URL for Signal receive endpoint from configured base URL."""
        parsed = urlparse(self._settings.base_url.rstrip("/"))
        if parsed.scheme == "http":
            scheme = "ws"
        elif parsed.scheme == "https":
            scheme = "wss"
        elif parsed.scheme in {"ws", "wss"}:
            scheme = parsed.scheme
        else:
            raise SignalAdapterInternalError(
                f"unsupported signal base_url scheme: {parsed.scheme or '<empty>'}"
            )
        base_path = parsed.path.rstrip("/")
        receive_path = (
            f"{base_path}/v1/receive/{quote(self._settings.receive_e164, safe='')}"
        )
        return urlunparse(
            (
                scheme,
                parsed.netloc,
                receive_path,
                "",
                "",
                "",
            )
        )

    def _flush_pending(self, *, registration: _WebhookRegistration) -> None:
        """Forward pending webhook bodies to Switchboard callback endpoint."""
        while len(self._pending_webhooks) > 0:
            body = self._pending_webhooks[0]
            callback_result = self._post_callback(
                registration=registration,
                raw_body_json=body,
            )
            self._log_callback_result(
                callback_result=callback_result,
                raw_body_json=body,
            )
            if callback_result.accepted and callback_result.queued:
                self._send_read_receipt(callback_result=callback_result)
            self._pending_webhooks.popleft()

    def _post_callback(
        self,
        *,
        registration: _WebhookRegistration,
        raw_body_json: str,
    ) -> _WebhookCallbackResult:
        """Send one signed webhook payload to the configured callback URL."""
        timestamp = int(time())
        signature = hmac.new(
            key=registration.shared_secret.encode("utf-8"),
            msg=f"{timestamp}.{raw_body_json}".encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            _HEADER_TIMESTAMP: str(timestamp),
            _HEADER_SIGNATURE: f"sha256={signature}",
        }

        try:
            response = self._callback_client.request_json(
                "POST",
                registration.callback_url,
                content=raw_body_json,
                headers=headers,
            )
        except HttpStatusError as exc:
            raise SignalAdapterDependencyError(
                f"switchboard callback failed with status {exc.status_code}"
            ) from None
        except HttpRequestError as exc:
            raise SignalAdapterDependencyError(
                str(exc) or "switchboard callback unavailable"
            ) from None
        except HttpJsonDecodeError as exc:
            raise SignalAdapterInternalError(
                f"switchboard callback response JSON invalid: {exc}"
            ) from None

        return self._parse_callback_result(response)

    def _parse_callback_result(self, response: object) -> _WebhookCallbackResult:
        """Validate one Switchboard callback response body."""
        if not isinstance(response, dict):
            raise SignalAdapterInternalError(
                "switchboard callback response must be a JSON object"
            )

        reason = str(response.get("reason") or "").strip()
        message = response.get("message")
        sender_e164 = ""
        timestamp_ms: int | None = None
        if isinstance(message, dict):
            sender = message.get("sender_e164")
            if sender is not None:
                sender_e164 = str(sender).strip()
            raw_timestamp = message.get("timestamp_ms")
            if raw_timestamp is not None:
                try:
                    timestamp_ms = int(str(raw_timestamp).strip())
                except ValueError:
                    timestamp_ms = None

        return _WebhookCallbackResult(
            accepted=bool(response.get("accepted", False)),
            queued=bool(response.get("queued", False)),
            reason=reason or "unspecified",
            sender_e164=sender_e164,
            timestamp_ms=timestamp_ms,
        )

    def _log_callback_result(
        self,
        *,
        callback_result: _WebhookCallbackResult,
        raw_body_json: str,
    ) -> None:
        """Emit one visible log line for Switchboard accept/reject decisions."""
        payload_summary = _summarize_signal_payload(raw_body_json)
        if callback_result.accepted and callback_result.queued:
            _LOGGER.info(
                "signal adapter callback acknowledged queued message",
                extra={
                    "reason": callback_result.reason,
                    "sender_e164": callback_result.sender_e164,
                    "timestamp_ms": callback_result.timestamp_ms,
                    **payload_summary,
                },
            )
            return

        _LOGGER.info(
            "signal adapter callback acknowledged without queueing",
            extra={
                "reason": callback_result.reason,
                "sender_e164": callback_result.sender_e164,
                "timestamp_ms": callback_result.timestamp_ms,
                **payload_summary,
            },
        )

    def _send_read_receipt(
        self,
        *,
        callback_result: _WebhookCallbackResult,
    ) -> None:
        """Send a read receipt after Switchboard confirms the message was queued."""
        if callback_result.sender_e164 == "" or callback_result.timestamp_ms is None:
            _LOGGER.warning(
                "signal adapter skipped read receipt after successful callback",
                extra={
                    "reason": "missing sender or timestamp",
                    "sender_e164": callback_result.sender_e164,
                    "timestamp_ms": callback_result.timestamp_ms,
                },
            )
            return

        path = f"/v1/receipts/{quote(self._settings.receive_e164, safe='')}"
        payload = {
            "receipt_type": "read",
            "recipient": callback_result.sender_e164,
            "timestamp": callback_result.timestamp_ms,
        }
        try:
            self._signal_client.post(path, json=payload)
        except HttpStatusError as exc:
            _LOGGER.warning(
                "signal adapter read receipt failed after successful callback: status %s",
                exc.status_code,
                extra={
                    "sender_e164": callback_result.sender_e164,
                    "timestamp_ms": callback_result.timestamp_ms,
                },
            )
        except HttpRequestError as exc:
            _LOGGER.warning(
                "signal adapter read receipt failed after successful callback: %s",
                str(exc) or "signal receipt unavailable",
                extra={
                    "sender_e164": callback_result.sender_e164,
                    "timestamp_ms": callback_result.timestamp_ms,
                },
            )

    def _get_registration(self) -> _WebhookRegistration | None:
        """Return latest callback registration snapshot."""
        with self._lock:
            return self._registration

    def _next_backoff_delay(self) -> float:
        """Return capped jittered backoff delay and advance backoff state."""
        base = min(
            self._backoff_seconds,
            self._settings.failure_backoff_max_seconds,
        )
        jitter = base * self._settings.failure_backoff_jitter_ratio * (random() * 2 - 1)
        delay = max(0.0, base + jitter)
        self._backoff_seconds = min(
            base * self._settings.failure_backoff_multiplier,
            self._settings.failure_backoff_max_seconds,
        )
        return delay


def _summarize_signal_payload(raw_body_json: str) -> dict[str, object]:
    """Summarize one raw Signal receive item for diagnostic logging."""
    try:
        payload = json.loads(raw_body_json)
    except json.JSONDecodeError:
        return {"payload_json_valid": False}
    if not isinstance(payload, dict):
        return {"payload_json_valid": True, "payload_type": type(payload).__name__}

    candidate = payload
    data = payload.get("data")
    if isinstance(data, dict):
        candidate = data

    envelope = candidate.get("envelope")
    if not isinstance(envelope, dict):
        envelope = {}
    exception = candidate.get("exception")
    if not isinstance(exception, dict):
        exception = {}

    data_message = envelope.get("dataMessage")
    sync_message = envelope.get("syncMessage")
    return {
        "payload_json_valid": True,
        "has_data_wrapper": isinstance(data, dict),
        "has_envelope": len(envelope) > 0,
        "has_data_message": isinstance(data_message, dict),
        "has_sync_message": isinstance(sync_message, dict),
        "exception_type": str(exception.get("type") or "").strip(),
        "exception_message": str(exception.get("message") or "").strip(),
        "source": str(
            envelope.get("source")
            or envelope.get("sourceNumber")
            or candidate.get("source")
            or candidate.get("sourceNumber")
            or ""
        ).strip(),
        "timestamp": str(
            envelope.get("timestamp") or candidate.get("timestamp") or ""
        ).strip(),
    }
