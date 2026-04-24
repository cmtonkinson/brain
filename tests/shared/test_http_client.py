"""Unit tests for shared HTTP client wrappers."""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from lib.shared.http import (
    AsyncHttpClient,
    HttpClient,
    HttpJsonDecodeError,
    HttpRequestError,
    HttpStatusError,
)
from lib.shared.http import client as http_client_module


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
            "/relay/poll_operator_instruction",
            log_operation="relay.poll_operator_instruction",
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
    assert completed.service == "relay"
    assert completed.operation == "relay.poll_operator_instruction"
    assert completed.endpoint == "/relay/poll_operator_instruction"
    assert completed.status_code == 200


# ---------------------------------------------------------------------------
# _status_error helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [500, 502, 503])
def test_status_error_marks_5xx_retryable(status_code: int) -> None:
    """5xx status codes should produce retryable=True errors."""
    request = httpx.Request("GET", "https://example.test/health")
    response = httpx.Response(status_code, text="fail", request=request)
    error = http_client_module._status_error(response)
    assert error.retryable is True
    assert error.status_code == status_code


def test_status_error_marks_429_retryable() -> None:
    """429 Too Many Requests should produce retryable=True."""
    request = httpx.Request("GET", "https://example.test/health")
    response = httpx.Response(429, text="rate limited", request=request)
    error = http_client_module._status_error(response)
    assert error.retryable is True
    assert error.status_code == 429


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
def test_status_error_marks_4xx_not_retryable(status_code: int) -> None:
    """4xx client errors (excluding 429) should produce retryable=False."""
    request = httpx.Request("GET", "https://example.test/health")
    response = httpx.Response(status_code, text="client error", request=request)
    error = http_client_module._status_error(response)
    assert error.retryable is False


# ---------------------------------------------------------------------------
# _request_log_fields helper
# ---------------------------------------------------------------------------


def test_request_log_fields_extracts_endpoint_from_url() -> None:
    """Log fields should extract the path as the endpoint."""
    fields = http_client_module._request_log_fields(
        method="GET",
        url="https://example.com/foo/bar?q=1",
        operation="test.op",
    )
    assert fields["endpoint"] == "/foo/bar"


def test_request_log_fields_extracts_service_from_operation() -> None:
    """Log fields should extract the service name from the operation prefix."""
    fields = http_client_module._request_log_fields(
        method="POST",
        url="https://example.com/vault/get",
        operation="vault.get_note",
    )
    assert fields["service"] == "vault"
    assert fields["operation"] == "vault.get_note"


def test_request_log_fields_omits_service_when_operation_empty() -> None:
    """Log fields should not include service key when operation is empty."""
    fields = http_client_module._request_log_fields(
        method="GET",
        url="https://example.com/health",
        operation="",
    )
    assert "service" not in fields
    assert "operation" not in fields


# ---------------------------------------------------------------------------
# Context manager behavior
# ---------------------------------------------------------------------------


def test_http_client_context_manager_closes_cleanly() -> None:
    """HttpClient should support with-statement and close on exit."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, request=request)

    with HttpClient(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = client.get_json("/health")
        assert result == {"ok": True}


# ---------------------------------------------------------------------------
# raise_for_status=False
# ---------------------------------------------------------------------------


def test_http_client_returns_error_response_when_raise_for_status_false() -> None:
    """Disabling raise_for_status should return error responses without raising."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal", request=request)

    with HttpClient(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        response = client.get("/health", raise_for_status=False)
        assert response.status_code == 500
        assert response.text == "internal"


# ---------------------------------------------------------------------------
# Client ownership
# ---------------------------------------------------------------------------


def test_http_client_does_not_close_externally_provided_client() -> None:
    """An externally provided httpx.Client should not be closed by the wrapper."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, request=request)

    external = httpx.Client(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    wrapper = HttpClient(client=external)
    wrapper.close()

    # External client should still be usable after wrapper closes.
    response = external.get("/health")
    assert response.status_code == 200
    external.close()
