"""Minimal FastAPI and uvicorn helpers for raw HTTP handling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import uvicorn
from fastapi import FastAPI, Request

from .errors import InvalidBodyError, InvalidJsonBodyError, MissingHeaderError


@dataclass(frozen=True)
class RawRequestData:
    """Raw inbound request body and normalized header mapping."""

    body: bytes
    headers: dict[str, str]


def create_app(*, title: str = "brain", version: str = "0.0.0") -> FastAPI:
    """Create a FastAPI app with project defaults."""
    return FastAPI(title=title, version=version)


def run_app(
    app: FastAPI,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    log_level: str = "info",
) -> None:
    """Run one FastAPI app through uvicorn."""
    uvicorn.run(app, host=host, port=port, log_level=log_level)


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
