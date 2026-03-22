"""Unit tests for shared HTTP client wrappers."""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from packages.brain_shared.http import (
    AsyncHttpClient,
    HttpClient,
    HttpJsonDecodeError,
    HttpRequestError,
    HttpStatusError,
)
from packages.brain_shared.http import client as http_client_module


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


def test_http_errors_allow_traceback_assignment() -> None:
    """HTTP helper exceptions must remain mutable enough for traceback wiring."""
    error = HttpRequestError(
        message="request failed",
        method="GET",
        url="https://example.test/health",
        retryable=True,
    )

    error.__traceback__ = None

    assert str(error) == "request failed"


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


def test_http_client_logs_operation_metadata() -> None:
    """HTTP client logs should include structured service and operation fields."""

    records: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, request=request)

    client = HttpClient(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    logger = http_client_module._LOGGER
    original_level = logger.level
    original_disabled = logger.disabled
    original_global_disable = logging.root.manager.disable
    capture_handler = _ListHandler()
    logger.addHandler(capture_handler)
    logger.disabled = False
    logging.disable(logging.NOTSET)
    logger.setLevel(logging.DEBUG)
    try:
        client.get_json(
            "/switchboard/poll_operator_instruction",
            log_operation="switchboard.poll_operator_instruction",
        )
    finally:
        logger.removeHandler(capture_handler)
        logger.setLevel(original_level)
        logger.disabled = original_disabled
        logging.disable(original_global_disable)
        client.close()

    completed = next(
        record
        for record in records
        if record.getMessage() == "HTTP client request completed"
    )
    assert completed.service == "switchboard"
    assert completed.operation == "switchboard.poll_operator_instruction"
    assert completed.endpoint == "/switchboard/poll_operator_instruction"
    assert completed.status_code == 200
