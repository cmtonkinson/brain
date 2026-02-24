"""Unit tests for shared HTTP client wrappers."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from packages.brain_shared.http import (
    AsyncHttpClient,
    HttpClient,
    HttpJsonDecodeError,
    HttpRequestError,
    HttpStatusError,
)


def test_http_client_get_json_returns_decoded_payload() -> None:
    """HttpClient.get_json should decode and return JSON content."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, request=request)

    client = HttpClient(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    try:
        assert client.get_json("/health") == {"ok": True}
    finally:
        client.close()


def test_http_client_maps_status_failure_to_typed_error() -> None:
    """HttpClient should raise HttpStatusError on non-2xx status codes."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable", request=request)

    client = HttpClient(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(HttpStatusError) as exc_info:
            client.get("/health")
    finally:
        client.close()

    error = exc_info.value
    assert error.method == "GET"
    assert error.status_code == 503
    assert error.retryable is True
    assert error.response_body == "unavailable"


def test_http_client_maps_transport_failure_to_typed_error() -> None:
    """HttpClient should raise HttpRequestError on transport failures."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    client = HttpClient(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(HttpRequestError) as exc_info:
            client.get("/health")
    finally:
        client.close()

    error = exc_info.value
    assert error.method == "GET"
    assert error.url == "https://example.test/health"
    assert error.retryable is True
    assert isinstance(error.cause, httpx.ConnectError)


def test_http_client_maps_json_decode_failure_to_typed_error() -> None:
    """HttpClient should raise HttpJsonDecodeError for invalid JSON payloads."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json", request=request)

    client = HttpClient(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(HttpJsonDecodeError) as exc_info:
            client.get_json("/health")
    finally:
        client.close()

    error = exc_info.value
    assert error.status_code == 200
    assert error.method == "GET"
    assert error.response_body == "not-json"


def test_async_http_client_post_json_returns_decoded_payload() -> None:
    """AsyncHttpClient.post_json should decode and return JSON content."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(200, json={"created": True}, request=request)

    client = AsyncHttpClient(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )

    async def _run() -> None:
        try:
            assert await client.post_json("/items", json={"name": "demo"}) == {
                "created": True
            }
        finally:
            await client.aclose()

    asyncio.run(_run())
