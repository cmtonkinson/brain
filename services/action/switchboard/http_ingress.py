"""HTTP ingress server for Switchboard webhook delivery."""

from __future__ import annotations

from http import HTTPStatus
from threading import Thread

import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse

from packages.brain_shared.envelope import EnvelopeKind, new_meta
from packages.brain_shared.errors import ErrorCategory
from packages.brain_shared.http import (
    InvalidBodyError,
    MissingHeaderError,
    create_app,
    get_header,
    read_text_body,
)
from services.action.switchboard.config import SwitchboardServiceSettings
from services.action.switchboard.domain import IngestResult
from services.action.switchboard.service import SwitchboardService

_HEADER_SIGNATURE = "X-Brain-Signature"
_HEADER_SIGNATURE_TIMESTAMP = "X-Brain-Timestamp"


class SwitchboardWebhookHttpServer:
    """Uvicorn-backed server exposing one Switchboard webhook callback endpoint."""

    def __init__(
        self,
        *,
        service: SwitchboardService,
        settings: SwitchboardServiceSettings,
    ) -> None:
        self._settings = settings
        self._app = create_switchboard_webhook_app(service=service, settings=settings)
        self._server = uvicorn.Server(
            uvicorn.Config(
                app=self._app,
                host=settings.webhook_bind_host,
                port=settings.webhook_bind_port,
                log_level="warning",
            )
        )
        self._thread: Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        """Return configured bind host/port tuple for this webhook server."""
        return self._settings.webhook_bind_host, self._settings.webhook_bind_port

    def start(self) -> None:
        """Start serving webhook requests in a background daemon thread."""
        if self._thread is not None:
            return
        self._thread = Thread(target=self._server.run, daemon=True)
        self._thread.start()

    def close(self) -> None:
        """Stop the server and release bound port resources."""
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


def create_switchboard_webhook_app(
    *,
    service: SwitchboardService,
    settings: SwitchboardServiceSettings,
):
    """Create one FastAPI app with the configured Switchboard webhook callback."""
    app = create_app(title="switchboard-webhook", version="1")

    @app.post(settings.webhook_path)
    async def ingest_signal_webhook(request: Request) -> JSONResponse:
        try:
            raw_body_json = await read_text_body(request)
            header_timestamp = get_header(request, _HEADER_SIGNATURE_TIMESTAMP)
            header_signature = get_header(request, _HEADER_SIGNATURE)
            assert header_timestamp is not None
            assert header_signature is not None
        except MissingHeaderError as exc:
            return JSONResponse(
                status_code=HTTPStatus.BAD_REQUEST,
                content={"ok": False, "error": str(exc)},
            )
        except InvalidBodyError as exc:
            return JSONResponse(
                status_code=HTTPStatus.BAD_REQUEST,
                content={"ok": False, "error": str(exc)},
            )

        result = service.ingest_signal_webhook(
            meta=new_meta(
                kind=EnvelopeKind.EVENT,
                source="switchboard_http_ingress",
                principal="operator",
            ),
            raw_body_json=raw_body_json,
            header_timestamp=header_timestamp,
            header_signature=header_signature,
        )
        if result.ok and result.payload is not None:
            payload = result.payload.value
            status = HTTPStatus.ACCEPTED if payload.accepted else HTTPStatus.OK
            return JSONResponse(
                status_code=status,
                content=_ingest_result_payload(payload=payload),
            )

        status_code = (
            _error_status(result.errors[0].category) if result.errors else HTTPStatus.OK
        )
        return JSONResponse(
            status_code=status_code,
            content={
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

    return app


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
