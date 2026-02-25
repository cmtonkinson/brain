"""In-process Signal adapter implementation over HTTP."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections import deque
from dataclasses import dataclass
from random import random
from threading import Event, Lock, Thread
from time import time
from urllib.parse import quote

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

_LOGGER = get_logger(__name__)
_HEADER_SIGNATURE = "X-Brain-Signature"
_HEADER_TIMESTAMP = "X-Brain-Timestamp"


@dataclass(frozen=True)
class _WebhookRegistration:
    callback_url: str
    shared_secret: str
    operator_e164: str


class HttpSignalAdapter(SignalAdapter):
    """Signal adapter backed by HTTP polling + webhook forwarding."""

    def __init__(self, *, settings: SignalAdapterSettings) -> None:
        self._settings = settings
        self._signal_client = HttpClient(
            base_url=settings.base_url.rstrip("/"),
            timeout_seconds=settings.timeout_seconds,
            headers={"Content-Type": "application/json"},
        )
        self._callback_client = HttpClient(timeout_seconds=settings.timeout_seconds)
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
        operator_e164: str,
    ) -> SignalWebhookRegistrationResult:
        """Configure callback target and start polling loop when needed."""
        registration = _WebhookRegistration(
            callback_url=callback_url.strip(),
            shared_secret=shared_secret.strip(),
            operator_e164=operator_e164.strip(),
        )
        if registration.callback_url == "":
            raise SignalAdapterInternalError("callback_url must be non-empty")
        if registration.shared_secret == "":
            raise SignalAdapterInternalError("shared_secret must be non-empty")
        if registration.operator_e164 == "":
            raise SignalAdapterInternalError("operator_e164 must be non-empty")

        with self._lock:
            self._registration = registration
            self._ensure_worker_started_locked()

        return SignalWebhookRegistrationResult(
            registered=True,
            detail="configured; polling loop active",
        )

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def health(self) -> SignalAdapterHealthResult:
        """Return adapter health by probing Signal runtime health endpoint."""
        try:
            self._signal_client.get("/health")
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
            detail=f"ok; callback={callback_state}; loop={loop_state}",
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
        """Poll Signal receive endpoint and forward messages to callback URL."""
        while not self._stop_event.is_set():
            delay = self._run_once()
            if delay > 0:
                self._stop_event.wait(delay)

    def _ensure_worker_started_locked(self) -> None:
        """Start polling worker once when callback registration is first configured."""
        if self._worker is not None:
            return
        self._stop_event.clear()
        self._worker = Thread(target=self._run_loop, daemon=True)
        self._worker.start()

    def _run_once(self) -> float:
        """Run one polling-forwarding cycle and return next sleep delay."""
        registration = self._get_registration()
        if registration is None:
            return self._settings.poll_interval_seconds

        try:
            if len(self._pending_webhooks) == 0:
                messages = self._receive_messages(
                    operator_e164=registration.operator_e164
                )
                for message in messages:
                    self._pending_webhooks.append(json.dumps({"data": message}))

            self._flush_pending(registration=registration)
            self._backoff_seconds = self._settings.failure_backoff_initial_seconds
            return self._settings.poll_interval_seconds
        except SignalAdapterDependencyError as exc:
            _LOGGER.warning(
                "signal adapter poll/forward dependency failure: %s",
                str(exc),
            )
            return self._next_backoff_delay()
        except SignalAdapterInternalError as exc:
            _LOGGER.error(
                "signal adapter poll/forward internal failure: %s",
                str(exc),
            )
            return self._next_backoff_delay()

    def _receive_messages(self, *, operator_e164: str) -> list[dict[str, object]]:
        """Receive one batch of Signal messages for the configured operator."""
        path = f"/v1/receive/{quote(operator_e164, safe='')}"
        params = {
            "timeout": str(self._settings.poll_receive_timeout_seconds),
            "max_messages": str(self._settings.poll_max_messages),
            "ignore_attachments": "true",
            "ignore_stories": "true",
            "send_read_receipts": "false",
        }
        for attempt in range(self._settings.max_retries + 1):
            try:
                payload = self._signal_client.get_json(path, params=params)
                if not isinstance(payload, list):
                    raise SignalAdapterInternalError(
                        "signal receive response must be a JSON array"
                    )
                messages: list[dict[str, object]] = []
                for item in payload:
                    if isinstance(item, dict):
                        messages.append(item)
                return messages
            except HttpStatusError as exc:
                if attempt < self._settings.max_retries:
                    continue
                raise SignalAdapterDependencyError(
                    f"signal receive failed with status {exc.status_code}"
                ) from None
            except HttpRequestError as exc:
                if attempt < self._settings.max_retries:
                    continue
                raise SignalAdapterDependencyError(
                    str(exc) or "signal receive unavailable"
                ) from None
            except HttpJsonDecodeError as exc:
                raise SignalAdapterInternalError(
                    f"signal receive response JSON invalid: {exc}"
                ) from None

        raise SignalAdapterDependencyError("signal receive unavailable")

    def _flush_pending(self, *, registration: _WebhookRegistration) -> None:
        """Forward pending webhook bodies to Switchboard callback endpoint."""
        while len(self._pending_webhooks) > 0:
            body = self._pending_webhooks[0]
            self._post_callback(registration=registration, raw_body_json=body)
            self._pending_webhooks.popleft()

    def _post_callback(
        self,
        *,
        registration: _WebhookRegistration,
        raw_body_json: str,
    ) -> None:
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
            self._callback_client.post(
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
