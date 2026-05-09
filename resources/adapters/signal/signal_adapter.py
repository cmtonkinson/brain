"""In-process Signal adapter implementation over signal-cli-rest-api."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass
from random import random
from threading import Event, Lock, Thread
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse, urlunparse

if TYPE_CHECKING:
    import httpx

import aiohttp

from lib.shared.auth.slash_authenticity import (
    SlashAuthenticityError,
    SlashAuthenticityProof,
    default_secret_path,
    mint_proof,
    new_nonce,
    read_secret,
)
from lib.shared.http import (
    HttpClient,
    HttpRequestError,
    HttpStatusError,
)
from lib.shared.envelope import EnvelopeKind, new_meta
from lib.shared.approval import normalize_approval_intent
from lib.shared.inbound_message import (
    InboundApproval,
    InboundMessage,
    InboundMessageRef,
    InboundReaction,
    InboundSender,
    InboundThreadRef,
)
from lib.shared.inbound_adapter import (
    InboundAdapterError,
    InboundAdapterHealthResult,
    InboundCallback,
    InboundCallbackRegistrationResult,
    InboundCallbackResult,
)
from lib.shared.inbound_text import (
    parse_links,
    parse_slash_command,
    parse_text_approval,
)
from lib.shared.logging import get_logger, public_api_instrumented
from lib.shared.phone_number import normalize_e164
from resources.adapters.signal.adapter import (
    SignalAdapter,
    SignalAdapterDependencyError,
    SignalAdapterInternalError,
    SignalSendMessageResult,
)
from resources.adapters.signal.component import RESOURCE_COMPONENT_ID
from resources.adapters.signal.config import SignalAdapterSettings

_LOGGER = get_logger(__name__)
_REGISTRATION_WAIT_SECONDS = 0.25
_RECEIVE_CHECK_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class _CallbackRegistration:
    callback: InboundCallback


class SignalRestApiAdapter(SignalAdapter):
    """Signal adapter backed by websocket receive and in-process callback flows."""

    def __init__(self, *, settings: SignalAdapterSettings) -> None:
        self._settings = settings
        self._signal_client = HttpClient(
            base_url=settings.base_url.rstrip("/"),
            timeout_seconds=settings.send_timeout_seconds,
            headers={"Content-Type": "application/json"},
        )
        self._lock = Lock()
        self._registration: _CallbackRegistration | None = None
        self._pending_payloads: deque[InboundMessage] = deque()
        self._worker: Thread | None = None
        self._stop_event = Event()
        self._backoff_seconds = settings.failure_backoff_initial_seconds

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def register_callback(
        self,
        *,
        callback: InboundCallback,
    ) -> InboundCallbackRegistrationResult:
        """Configure callback target and start receive loop when needed."""
        registration = _CallbackRegistration(callback=callback)

        with self._lock:
            self._registration = registration
            self._ensure_worker_started_locked()

        return InboundCallbackRegistrationResult(
            registered=True,
            detail="configured; receive loop active",
        )

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def health(self) -> InboundAdapterHealthResult:
        """Return local adapter readiness independent of provider reachability."""
        with self._lock:
            registration = self._registration
            worker_alive = self._worker is not None and self._worker.is_alive()
        callback_state = "configured" if registration is not None else "unconfigured"
        loop_state = "running" if worker_alive else "stopped"
        return InboundAdapterHealthResult(
            adapter_ready=True,
            detail=f"ready; callback={callback_state}; receive_loop={loop_state}",
        )

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def mint_slash_authenticity_proof(
        self,
        *,
        channel: str,
        message_text: str,
    ) -> SlashAuthenticityProof:
        """Sign an operator-channel slash command with the on-disk HMAC secret.

        Reads the secret on every call so a Brain Core restart (which rotates
        the file) is picked up without an Adapter restart.
        """
        try:
            secret = read_secret(default_secret_path())
        except SlashAuthenticityError as exc:
            raise SignalAdapterDependencyError(
                f"slash authenticity secret unavailable: {exc}"
            ) from None
        return mint_proof(
            secret,
            channel=channel,
            message_text=message_text,
            now_ms=int(time.time() * 1000),
            nonce=new_nonce(),
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
        _LOGGER.verbose(
            "signal adapter send_message request captured",
            extra={
                "sender_e164": sender,
                "recipient_e164": recipient,
                "signal_request_payload": payload,
            },
        )
        try:
            response = self._signal_client.post("/v2/send", json=payload)
        except HttpStatusError as exc:
            raise SignalAdapterDependencyError(
                f"signal send failed with status {exc.status_code}"
            ) from None
        except HttpRequestError as exc:
            raise SignalAdapterDependencyError(
                str(exc) or "signal send unavailable"
            ) from None

        response_payload, sent_timestamp_ms = _response_payload_and_timestamp_ms(
            response
        )
        _LOGGER.verbose(
            "signal adapter send_message response captured",
            extra={
                "sender_e164": sender,
                "recipient_e164": recipient,
                "signal_response_payload": response_payload,
                "sent_timestamp_ms": sent_timestamp_ms,
            },
        )

        return SignalSendMessageResult(
            delivered=True,
            recipient_e164=recipient,
            sender_e164=sender,
            detail="delivered",
            sent_timestamp_ms=sent_timestamp_ms,
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
                asyncio.run(
                    self._run_receive_session(registration=registration)
                )  # asyncio.run() is correct here — creates a fresh event loop per session; do not hoist
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
                _LOGGER.error(
                    "signal adapter receive/forward internal failure: %s",
                    str(exc),
                )
                return self._next_backoff_delay()

    def _ensure_worker_started_locked(self) -> None:
        """Start receive worker once when callback registration is configured."""
        if self._worker is not None:
            return
        self._stop_event.clear()
        self._worker = Thread(target=self._run_loop, daemon=True)
        self._worker.start()

    async def _run_receive_session(
        self, *, registration: _CallbackRegistration
    ) -> None:
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
        registration: _CallbackRegistration,
        raw_payload_json: str,
    ) -> None:
        """Parse one websocket payload and forward its contained Signal items."""
        _LOGGER.verbose(
            "signal adapter received websocket payload",
            extra={
                "raw_payload_json": raw_payload_json,
                **_summarize_signal_receive_payload(raw_payload_json),
            },
        )
        payloads = self._decode_receive_payload(raw_payload_json)
        for payload in payloads:
            wrapped_body = json.dumps({"data": payload})
            _LOGGER.verbose(
                "signal adapter queued callback payload",
                extra={
                    "raw_body_json": wrapped_body,
                    **summarize_signal_payload(wrapped_body),
                },
            )
            message = self._normalize_inbound_payload(payload)
            if message is None:
                continue
            self._pending_payloads.append(message)
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

    def _flush_pending(self, *, registration: _CallbackRegistration) -> None:
        """Forward pending receive payloads to the registered callback."""
        while self._pending_payloads:
            message = self._pending_payloads[0]
            callback_result = self._invoke_callback(
                registration=registration,
                message=message,
            )
            self._log_callback_result(
                callback_result=callback_result,
                message=message,
            )
            if callback_result.accepted and callback_result.queued:
                self._send_read_receipt(callback_result=callback_result)
            self._pending_payloads.popleft()

    def _invoke_callback(
        self,
        *,
        registration: _CallbackRegistration,
        message: InboundMessage,
    ) -> InboundCallbackResult:
        """Invoke the configured in-process callback for one receive payload."""
        try:
            return registration.callback(
                meta=new_meta(
                    kind=EnvelopeKind.EVENT,
                    source=str(RESOURCE_COMPONENT_ID),
                    principal="operator",
                ),
                message=message,
            )
        except InboundAdapterError:
            raise
        except Exception as exc:
            raise SignalAdapterInternalError(
                f"signal inbound callback failed: {exc}"
            ) from None

    def _log_callback_result(
        self,
        *,
        callback_result: InboundCallbackResult,
        message: InboundMessage,
    ) -> None:
        """Emit one visible log line for Relay inbound accept/reject decisions."""
        if callback_result.accepted and callback_result.queued:
            _LOGGER.info(
                "signal adapter callback accepted queued message",
                extra={
                    "reason": callback_result.reason,
                    "sender_e164": callback_result.sender_e164,
                    "timestamp_ms": callback_result.timestamp_ms,
                    "channel": message.channel,
                },
            )
            return

        _LOGGER.info(
            "signal adapter callback completed without queueing",
            extra={
                "reason": callback_result.reason,
                "sender_e164": callback_result.sender_e164,
                "timestamp_ms": callback_result.timestamp_ms,
                "channel": message.channel,
            },
        )

    def _normalize_inbound_payload(
        self, payload: dict[str, object]
    ) -> InboundMessage | None:
        """Normalize one Signal provider payload into the shared inbound DTO."""
        candidate: dict[str, Any] = dict(payload)
        data = candidate.get("data")
        if isinstance(data, dict):
            candidate = dict(data)
        envelope = _extract_envelope(candidate)
        message_payload = _extract_message_payload(envelope)

        sender_raw = _first_non_empty(
            envelope,
            "source",
            "sourceNumber",
            "sender",
            "from",
            "sender_e164",
        )
        if sender_raw == "":
            return None
        try:
            sender_e164 = normalize_e164(
                raw=sender_raw,
                default_dial_code=self._settings.default_dial_code,
            )
        except ValueError:
            return None

        timestamp_ms = _parse_timestamp_ms(
            envelope.get("timestamp_ms")
            or envelope.get("timestamp")
            or envelope.get("sourceTimestamp")
            or candidate.get("timestamp_ms")
            or candidate.get("timestamp")
            or candidate.get("sourceTimestamp")
        )
        if timestamp_ms is None:
            return None

        message_text = _first_non_empty(
            message_payload,
            "message",
            "message_text",
            "text",
            "body",
        )
        if message_text == "":
            message_text = _first_non_empty(
                envelope,
                "message",
                "message_text",
                "text",
                "body",
            )
        if message_text == "":
            message_text = _first_non_empty(
                candidate,
                "message",
                "message_text",
                "text",
                "body",
            )

        reply_timestamp_ms = _optional_int(
            _extract_nested(message_payload, "quote", "timestamp")
            or _extract_nested(message_payload, "quote", "id")
            or candidate.get("quote_target_timestamp_ms")
        )
        reaction_timestamp_ms = _optional_int(
            _extract_nested(message_payload, "reaction", "targetSentTimestamp")
            or _extract_nested(message_payload, "reaction", "targetTimestamp")
            or candidate.get("reaction_target_timestamp_ms")
        )
        reaction_text = _extract_reaction_text(message_payload) or _first_non_empty(
            candidate,
            "reaction_emoji",
            "reaction_text",
        )
        if message_text == "" and reaction_timestamp_ms is None and reaction_text == "":
            return None

        approval = parse_text_approval(message_text)
        reaction_intent = normalize_approval_intent(reaction_emoji=reaction_text)
        if reaction_intent is not None:
            approval = InboundApproval(intent=reaction_intent, source="reaction")

        source_device = str(
            envelope.get("sourceDevice")
            or envelope.get("source_device")
            or candidate.get("sourceDevice")
            or candidate.get("device")
            or candidate.get("source_device")
            or ""
        )
        group_id = _extract_group_id(message_payload) or _extract_group_id(envelope)
        return InboundMessage(
            channel="signal",
            sender=InboundSender(id=sender_e164, e164=sender_e164),
            message_text=message_text,
            timestamp_ms=timestamp_ms,
            source_device=source_device,
            thread=None if group_id is None else InboundThreadRef(id=group_id),
            reply_to=(
                None
                if reply_timestamp_ms is None
                else InboundMessageRef(timestamp_ms=reply_timestamp_ms)
            ),
            reaction=(
                None
                if reaction_text == "" and reaction_timestamp_ms is None
                else InboundReaction(
                    text=reaction_text,
                    target=(
                        None
                        if reaction_timestamp_ms is None
                        else InboundMessageRef(timestamp_ms=reaction_timestamp_ms)
                    ),
                )
            ),
            links=parse_links(message_text),
            approval=approval,
            slash_command=parse_slash_command(message_text),
            raw_metadata={"payload_shape": _signal_payload_shape(candidate)},
        )

    def _send_read_receipt(
        self,
        *,
        callback_result: InboundCallbackResult,
    ) -> None:
        """Send a read receipt after Relay inbound confirms the message was queued."""
        if callback_result.sender_e164 is None or callback_result.timestamp_ms is None:
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
        _LOGGER.verbose(
            "signal adapter read receipt request captured",
            extra={
                "signal_request_payload": payload,
                "sender_e164": self._settings.receive_e164,
                "recipient_e164": callback_result.sender_e164,
            },
        )
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

    def _get_registration(self) -> _CallbackRegistration | None:
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


def _response_payload_and_timestamp_ms(
    response: "httpx.Response",
) -> tuple[object | None, int | None]:
    """Extract one outbound send response payload plus its timestamp when present."""
    try:
        payload = response.json()
    except Exception:
        return None, None

    if isinstance(payload, dict):
        candidate = payload.get("timestamp") or payload.get("timestamp_ms")
        return payload, _optional_int(candidate)
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            candidate = item.get("timestamp") or item.get("timestamp_ms")
            parsed = _optional_int(candidate)
            if parsed is not None:
                return payload, parsed
        return payload, None
    return payload, None


def _optional_int(value: object) -> int | None:
    """Parse one optional integer value when present."""
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _extract_group_id(payload: dict[str, Any]) -> str | None:
    """Extract optional group identifier from common Signal payload shapes."""
    group_id = payload.get("group_id")
    if isinstance(group_id, str) and group_id.strip() != "":
        return group_id
    group_info = payload.get("groupInfo")
    if isinstance(group_info, dict):
        group_id = group_info.get("groupId") or group_info.get("id")
        if isinstance(group_id, str) and group_id.strip() != "":
            return group_id
    return None


def _extract_reaction_text(payload: dict[str, Any]) -> str:
    """Extract one reaction marker from common Signal payload shapes."""
    reaction = payload.get("reaction")
    if not isinstance(reaction, dict):
        return ""
    return _first_non_empty(reaction, "emoji", "emojiShortName", "emoji_short_name")


def _signal_payload_shape(candidate: dict[str, Any]) -> str:
    """Return a stable description of the normalized payload shape."""
    envelope = candidate.get("envelope")
    if not isinstance(envelope, dict):
        return "candidate"
    if isinstance(envelope.get("dataMessage"), dict):
        return "envelope.dataMessage"
    if isinstance(envelope.get("syncMessage"), dict):
        return "envelope.syncMessage"
    return "envelope"


def _extract_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Return nested Signal envelope when present; otherwise the payload itself."""
    envelope = payload.get("envelope")
    if isinstance(envelope, dict):
        return envelope
    return payload


def _extract_message_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the nested message object most likely to contain message fields."""
    data_message = payload.get("dataMessage")
    if isinstance(data_message, dict):
        return data_message
    sync_message = payload.get("syncMessage")
    if isinstance(sync_message, dict):
        sent_message = sync_message.get("sentMessage")
        if isinstance(sent_message, dict):
            return sent_message
    return payload


def _extract_nested(payload: dict[str, Any], parent: str, child: str) -> Any:
    """Read one nested mapping field when parent is an object."""
    parent_value = payload.get(parent)
    if isinstance(parent_value, dict):
        return parent_value.get(child)
    return None


def _first_non_empty(payload: dict[str, Any], *keys: str) -> str:
    """Return first non-empty scalar string value for the provided keys."""
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        candidate = str(value).strip()
        if candidate != "":
            return candidate
    return ""


def _parse_timestamp_ms(value: Any) -> int | None:
    """Parse inbound Signal timestamps in seconds or milliseconds to milliseconds."""
    parsed = _optional_int(value)
    if parsed is None:
        return None
    if parsed < 1_000_000_000_000:
        return parsed * 1000
    return parsed


def summarize_signal_payload(raw_body_json: str) -> dict[str, object]:
    """Summarize one raw Signal receive item for diagnostic logging.

    Expects the callback-wrapped ``{"data": {...}}`` format. Tolerates the
    unwrapped envelope form so service-side callers can use this on either
    shape.
    """
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
    if not isinstance(candidate, dict):
        return {"payload_json_valid": True, "payload_type": type(candidate).__name__}

    envelope = candidate.get("envelope")
    if not isinstance(envelope, dict):
        envelope = {}
    exception = candidate.get("exception")
    if not isinstance(exception, dict):
        exception = {}

    return {
        "payload_json_valid": True,
        "has_data_wrapper": isinstance(data, dict),
        "has_envelope": len(envelope) > 0,
        "has_data_message": isinstance(envelope.get("dataMessage"), dict),
        "has_sync_message": isinstance(envelope.get("syncMessage"), dict),
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


def _summarize_signal_receive_payload(raw_payload_json: str) -> dict[str, object]:
    """Summarize one raw Signal websocket payload before callback wrapping.

    Expects the raw websocket frame, before ``{"data": ...}`` wrapping.
    """
    try:
        payload = json.loads(raw_payload_json)
    except json.JSONDecodeError:
        return {"payload_json_valid": False}

    if isinstance(payload, list):
        return {
            "payload_json_valid": True,
            "payload_type": "list",
            "item_count": len(payload),
            "contains_quote": any(_payload_contains_quote(item) for item in payload),
            "contains_reaction": any(
                _payload_contains_reaction(item) for item in payload
            ),
        }
    if isinstance(payload, dict):
        return {
            "payload_json_valid": True,
            "payload_type": "dict",
            "contains_quote": _payload_contains_quote(payload),
            "contains_reaction": _payload_contains_reaction(payload),
        }
    return {"payload_json_valid": True, "payload_type": type(payload).__name__}


def _payload_contains_quote(payload: object) -> bool:
    """Return whether one raw Signal payload contains quoted-reply metadata."""
    if not isinstance(payload, dict):
        return False
    envelope = payload.get("envelope")
    if not isinstance(envelope, dict):
        return False
    data_message = envelope.get("dataMessage")
    if not isinstance(data_message, dict):
        return False
    return isinstance(data_message.get("quote"), dict)


def _payload_contains_reaction(payload: object) -> bool:
    """Return whether one raw Signal payload contains reaction metadata."""
    if not isinstance(payload, dict):
        return False
    envelope = payload.get("envelope")
    if not isinstance(envelope, dict):
        return False
    data_message = envelope.get("dataMessage")
    if not isinstance(data_message, dict):
        return False
    return isinstance(data_message.get("reaction"), dict)
