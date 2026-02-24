"""HTTP ingress server for Switchboard webhook delivery."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from packages.brain_shared.envelope import EnvelopeKind, new_meta
from packages.brain_shared.errors import ErrorCategory
from services.action.switchboard.config import SwitchboardServiceSettings
from services.action.switchboard.domain import IngestResult
from services.action.switchboard.service import SwitchboardService

_HEADER_SIGNATURE = "X-Signature"
_HEADER_SIGNATURE_TIMESTAMP = "X-Signature-Timestamp"


class SwitchboardWebhookHttpServer:
    """Minimal HTTP server exposing one Switchboard webhook callback endpoint."""

    def __init__(
        self,
        *,
        service: SwitchboardService,
        settings: SwitchboardServiceSettings,
    ) -> None:
        self._service = service
        self._settings = settings
        self._server = ThreadingHTTPServer(
            (settings.webhook_bind_host, settings.webhook_bind_port),
            _build_handler(service=service, settings=settings),
        )
        self._thread: Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        """Return bound host/port tuple for this webhook server."""
        host, port = self._server.server_address
        return str(host), int(port)

    def start(self) -> None:
        """Start serving webhook requests in a background daemon thread."""
        if self._thread is not None:
            return
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        """Stop the server and release bound port resources."""
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


def _build_handler(
    *,
    service: SwitchboardService,
    settings: SwitchboardServiceSettings,
) -> type[BaseHTTPRequestHandler]:
    """Build one request handler class bound to service and settings context."""

    class _SwitchboardWebhookHandler(BaseHTTPRequestHandler):
        """Request handler that forwards webhook payloads to Switchboard service."""

        def do_POST(self) -> None:  # noqa: N802
            if self.path != settings.webhook_path:
                self._write_json(
                    status=HTTPStatus.NOT_FOUND,
                    payload={"ok": False, "error": "not found"},
                )
                return

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                content_length = 0
            raw_body = self.rfile.read(content_length)
            try:
                raw_body_json = raw_body.decode("utf-8")
            except UnicodeDecodeError:
                self._write_json(
                    status=HTTPStatus.BAD_REQUEST,
                    payload={"ok": False, "error": "payload must be UTF-8 JSON text"},
                )
                return

            result = service.ingest_signal_webhook(
                meta=new_meta(
                    kind=EnvelopeKind.EVENT,
                    source="switchboard_http_ingress",
                    principal="operator",
                ),
                raw_body_json=raw_body_json,
                header_timestamp=self.headers.get(_HEADER_SIGNATURE_TIMESTAMP, ""),
                header_signature=self.headers.get(_HEADER_SIGNATURE, ""),
            )
            if result.ok and result.payload is not None:
                payload = result.payload.value
                status = HTTPStatus.ACCEPTED if payload.accepted else HTTPStatus.OK
                self._write_json(
                    status=status,
                    payload=_ingest_result_payload(payload=payload),
                )
                return

            status = _error_status(result.errors[0].category) if result.errors else 500
            self._write_json(
                status=HTTPStatus(status),
                payload={
                    "ok": False,
                    "errors": [
                        {
                            "code": error.code,
                            "category": error.category.value,
                            "message": error.message,
                        }
                        for error in result.errors
                    ],
                },
            )

        def log_message(self, format: str, *args: object) -> None:
            """Disable stdlib per-request stderr logging."""
            del format, args

        def _write_json(
            self, *, status: HTTPStatus, payload: dict[str, object]
        ) -> None:
            """Write one JSON response body with common headers."""
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _SwitchboardWebhookHandler


def _ingest_result_payload(*, payload: IngestResult) -> dict[str, object]:
    """Convert ingest result into HTTP-friendly JSON payload."""
    response: dict[str, object] = {
        "ok": True,
        "accepted": payload.accepted,
        "queued": payload.queued,
        "queue_name": payload.queue_name,
        "reason": payload.reason,
    }
    if payload.message is not None:
        response["message"] = payload.message.model_dump(mode="python")
    return response


def _error_status(category: ErrorCategory) -> int:
    """Map structured envelope error category to HTTP status code."""
    if category == ErrorCategory.VALIDATION:
        return HTTPStatus.BAD_REQUEST
    if category == ErrorCategory.POLICY:
        return HTTPStatus.FORBIDDEN
    if category == ErrorCategory.DEPENDENCY:
        return HTTPStatus.SERVICE_UNAVAILABLE
    if category == ErrorCategory.INTERNAL:
        return HTTPStatus.INTERNAL_SERVER_ERROR
    return HTTPStatus.BAD_REQUEST
