"""Unit tests for shared FastAPI/uvicorn HTTP server helpers."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import Request

from packages.brain_shared.http import (
    InvalidBodyError,
    InvalidJsonBodyError,
    MissingHeaderError,
    create_app,
    get_header,
    read_json_body,
    read_raw_body,
    read_raw_request,
    read_text_body,
    run_app,
)


def _request(body: bytes = b"", headers: dict[str, str] | None = None) -> Request:
    """Create a minimal Starlette request object for helper tests."""
    sent = False
    normalized_headers = {
        "host": "test.local",
        **(headers or {}),
    }
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in normalized_headers.items()
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
        "root_path": "",
    }

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive=receive)


def test_create_app_returns_fastapi_app() -> None:
    """create_app should return a FastAPI instance with configured metadata."""
    app = create_app(title="brain-test", version="1.2.3")
    assert app.title == "brain-test"
    assert app.version == "1.2.3"


def test_get_header_returns_trimmed_value() -> None:
    """get_header should return the requested header value by default."""
    request = _request(headers={"x-signature": "  abc123  "})

    assert get_header(request, "x-signature") == "abc123"


def test_get_header_raises_for_missing_required_header() -> None:
    """get_header should raise MissingHeaderError for required missing headers."""
    request = _request(headers={})

    with pytest.raises(MissingHeaderError) as exc_info:
        get_header(request, "x-signature")

    assert exc_info.value.header_name == "x-signature"


def test_get_header_returns_none_for_missing_optional_header() -> None:
    """get_header should return None for missing optional headers."""
    request = _request(headers={})

    assert get_header(request, "x-signature", required=False) is None


def test_read_raw_and_text_body_success() -> None:
    """read_raw_body and read_text_body should decode one UTF-8 payload."""
    request = _request(body=b'{"ok":true}')

    async def _run() -> None:
        assert await read_raw_body(request) == b'{"ok":true}'
        assert await read_text_body(_request(body=b"hello")) == "hello"

    asyncio.run(_run())


def test_read_text_body_raises_invalid_body_for_decode_error() -> None:
    """read_text_body should raise InvalidBodyError on decode failures."""
    request = _request(body=b"\xff")

    async def _run() -> None:
        with pytest.raises(InvalidBodyError):
            await read_text_body(request)

    asyncio.run(_run())


def test_read_json_body_decodes_json_and_maps_decode_error() -> None:
    """read_json_body should decode JSON and map invalid bodies."""

    async def _run() -> None:
        assert await read_json_body(_request(body=b'{"ok": true}')) == {"ok": True}

        with pytest.raises(InvalidJsonBodyError):
            await read_json_body(_request(body=b"{not-json"))

    asyncio.run(_run())


def test_read_raw_request_returns_body_and_headers() -> None:
    """read_raw_request should return both raw body bytes and headers."""
    request = _request(body=b"payload", headers={"x-token": "abc"})

    async def _run() -> None:
        raw = await read_raw_request(request)
        assert raw.body == b"payload"
        assert raw.headers["x-token"] == "abc"

    asyncio.run(_run())


def test_run_app_forwards_arguments_to_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_app should delegate execution to uvicorn.run with provided options."""
    app = create_app()
    called: dict[str, Any] = {}

    def _fake_run(target: Any, **kwargs: Any) -> None:
        called["target"] = target
        called["kwargs"] = kwargs

    monkeypatch.setattr("packages.brain_shared.http.server.uvicorn.run", _fake_run)

    run_app(app, host="0.0.0.0", port=9999, log_level="debug")

    assert called["target"] is app
    assert called["kwargs"] == {
        "host": "0.0.0.0",
        "port": 9999,
        "log_level": "debug",
    }
