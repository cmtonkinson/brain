"""Minimal FastAPI and uvicorn helpers for raw HTTP handling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response

from .errors import InvalidBodyError, InvalidJsonBodyError, MissingHeaderError
from packages.brain_shared.logging import get_logger

_LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class RawRequestData:
    """Raw inbound request body and normalized header mapping."""

    body: bytes
    headers: dict[str, str]


def create_app(
    *,
    title: str = "brain",
    version: str = "0.0.0",
    log_requests: bool = True,
) -> FastAPI:
    """Create a FastAPI app with project defaults."""
    app = FastAPI(title=title, version=version)
    if log_requests:
        _install_request_logging(app)
    return app


def run_app(
    app: FastAPI,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    log_level: str = "info",
) -> None:
    """Run one FastAPI app through uvicorn."""
    uvicorn.run(app, host=host, port=port, log_level=log_level)


def run_app_uds(
    app: FastAPI,
    *,
    socket_path: str,
    log_level: str = "warning",
) -> uvicorn.Server:
    """Create a uvicorn Server serving app over a Unix Domain Socket."""
    config = uvicorn.Config(app, uds=socket_path, log_level=log_level)
    return uvicorn.Server(config)


def _install_request_logging(app: FastAPI) -> None:
    """Attach one lightweight middleware for per-request summary logs."""

    @app.middleware("http")
    async def _log_request(request: Request, call_next) -> Response:
        started = perf_counter()
        response = await call_next(request)
        duration_ms = round((perf_counter() - started) * 1000, 2)
        _LOGGER.debug(
            "HTTP request handled",
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


def get_header(
    request: Request,
    name: str,
    *,
    required: bool = True,
    strip: bool = True,
) -> str | None:
    """Fetch one header value and optionally enforce presence."""
    value = request.headers.get(name)
    if value is None:
        if required:
            raise MissingHeaderError(
                message=f"Missing required header: {name}",
                header_name=name,
            )
        return None

    if strip:
        value = value.strip()
    if required and value == "":
        raise MissingHeaderError(
            message=f"Missing required header: {name}",
            header_name=name,
        )
    return value


async def read_raw_body(request: Request) -> bytes:
    """Read raw request body bytes without interpretation."""
    return await request.body()


async def read_text_body(request: Request, *, encoding: str = "utf-8") -> str:
    """Read and decode one request body as text."""
    body = await read_raw_body(request)
    try:
        return body.decode(encoding)
    except UnicodeDecodeError as exc:
        raise InvalidBodyError(
            message=f"Body decode failed with encoding {encoding}",
        ) from exc


async def read_json_body(request: Request) -> Any:
    """Read and decode one request body as JSON."""
    body = await read_raw_body(request)
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise InvalidJsonBodyError(message="Body is not valid JSON") from exc


async def read_raw_request(request: Request) -> RawRequestData:
    """Read raw body and all headers for manual downstream handling."""
    body = await read_raw_body(request)
    headers = dict(request.headers.items())
    return RawRequestData(body=body, headers=headers)
