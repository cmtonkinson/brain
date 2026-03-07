"""Tiny local HTTP server for asserting Signal adapter wire payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any


@dataclass(slots=True)
class CapturedSignalRequest:
    """One HTTP request captured by the fake Signal server."""

    method: str
    path: str
    headers: dict[str, str]
    body: dict[str, Any]


@dataclass(slots=True)
class FakeSignalServer:
    """Context-managed local HTTP server that captures Signal requests."""

    status_code: int = 201
    response_json: dict[str, Any] = field(default_factory=lambda: {"ok": True})
    requests: list[CapturedSignalRequest] = field(default_factory=list, init=False)
    _server: ThreadingHTTPServer = field(init=False)
    _thread: Thread = field(init=False)

    def __post_init__(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_type())
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        """Return server base URL suitable for adapter configuration."""
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> "FakeSignalServer":
        """Start serving on context entry."""
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        """Stop serving on context exit."""
        self.close()

    def close(self) -> None:
        """Stop the server and wait briefly for thread exit."""
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        parent = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length).decode("utf-8")
                body = json.loads(raw) if raw.strip() else {}
                parent.requests.append(
                    CapturedSignalRequest(
                        method="POST",
                        path=self.path,
                        headers={key: value for key, value in self.headers.items()},
                        body=body if isinstance(body, dict) else {"_raw": body},
                    )
                )
                payload = json.dumps(parent.response_json).encode("utf-8")
                self.send_response(parent.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        return _Handler
