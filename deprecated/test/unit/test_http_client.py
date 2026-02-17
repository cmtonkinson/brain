"""Unit tests for HTTP client wrapper with error handling and retries."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
import pytest

from config import settings
from services.http_client import (
    AsyncHttpClient,
    ErrorConfig,
    ErrorStrategy,
    HttpClient,
    RetryConfig,
)


def _build_response(
    status_code: int,
    *,
    json_data: object | None = None,
    content: str | bytes | None = None,
    method: str = "GET",
    url: str = "http://test.example",
) -> httpx.Response:
    """Create a synthetic httpx response with a bound request."""
    request = httpx.Request(method, url)
    return httpx.Response(status_code=status_code, json=json_data, content=content, request=request)


class StubAsyncClient:
    """Async client stub returning configured responses."""

    def __init__(self, responses: list[httpx.Response | Exception] | None = None) -> None:
        """Initialize the stub with a sequence of responses or exceptions.

        Args:
            responses: List of responses or exceptions to return in order.
                      Each call consumes one item from the list.
        """
        self.responses = responses or []
        self.call_count = 0

    async def __aenter__(self) -> "StubAsyncClient":
        """Enter the async context manager."""
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Exit the async context manager."""
        pass

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Return the next configured response or raise the next configured error."""
        if self.call_count >= len(self.responses):
            # Default success response if we run out
            return _build_response(200, json_data={}, method=method, url=url)

        response_or_error = self.responses[self.call_count]
        self.call_count += 1

        if isinstance(response_or_error, Exception):
            raise response_or_error
        return response_or_error


class StubSyncClient:
    """Synchronous client stub returning configured responses."""

    def __init__(self, responses: list[httpx.Response | Exception] | None = None) -> None:
        """Initialize the stub with a sequence of responses or exceptions."""
        self.responses = responses or []
        self.call_count = 0

    def __enter__(self) -> "StubSyncClient":
        """Enter the context manager."""
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Exit the context manager."""
        pass

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Return the next configured response or raise the next configured error."""
        if self.call_count >= len(self.responses):
            # Default success response if we run out
            return _build_response(200, json_data={}, method=method, url=url)

        response_or_error = self.responses[self.call_count]
        self.call_count += 1

        if isinstance(response_or_error, Exception):
            raise response_or_error
        return response_or_error


# ==================== AsyncHttpClient Tests ====================


@pytest.mark.asyncio
async def test_async_client_default_timeout_from_settings(monkeypatch) -> None:
    """AsyncHttpClient uses settings.http.timeout by default."""
    monkeypatch.setattr(settings.http, "timeout", 42, raising=False)
    monkeypatch.setattr(settings.http, "connect_timeout", 7, raising=False)

    client = AsyncHttpClient()
    assert client.timeout == 42
    assert client.connect_timeout == 7


@pytest.mark.asyncio
async def test_async_client_custom_timeout_override(monkeypatch) -> None:
    """AsyncHttpClient accepts custom timeout overrides."""
    monkeypatch.setattr(settings.http, "timeout", 30, raising=False)

    client = AsyncHttpClient(timeout=120, connect_timeout=15)
    assert client.timeout == 120
    assert client.connect_timeout == 15


@pytest.mark.asyncio
async def test_async_client_get_success(monkeypatch) -> None:
    """AsyncHttpClient.get returns response on success."""
    response = _build_response(200, json_data={"result": "ok"}, method="GET")
    stub = StubAsyncClient(responses=[response])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: stub)

    client = AsyncHttpClient()
    result = await client.get("http://test.example/api")

    assert result is not None
    assert result.status_code == 200
    assert result.json() == {"result": "ok"}


@pytest.mark.asyncio
async def test_async_client_post_success(monkeypatch) -> None:
    """AsyncHttpClient.post returns response on success."""
    response = _build_response(201, json_data={"created": True}, method="POST")
    stub = StubAsyncClient(responses=[response])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: stub)

    client = AsyncHttpClient()
    result = await client.post("http://test.example/api", json={"data": "test"})

    assert result is not None
    assert result.status_code == 201
    assert result.json() == {"created": True}


@pytest.mark.asyncio
async def test_async_client_error_strategy_raise(monkeypatch) -> None:
    """AsyncHttpClient with RAISE strategy re-raises exceptions."""
    error_response = _build_response(500, json_data={"error": "fail"}, method="GET")
    error = httpx.HTTPStatusError(
        "Server error", request=error_response.request, response=error_response
    )
    stub = StubAsyncClient(responses=[error])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: stub)

    client = AsyncHttpClient(error_config=ErrorConfig(strategy=ErrorStrategy.RAISE))

    with pytest.raises(httpx.HTTPStatusError):
        await client.get("http://test.example/api")


@pytest.mark.asyncio
async def test_async_client_error_strategy_log_and_return_none(monkeypatch, caplog) -> None:
    """AsyncHttpClient with LOG_AND_RETURN_NONE logs error and returns None."""
    error_response = _build_response(404, json_data={"error": "not found"}, method="GET")
    error = httpx.HTTPStatusError(
        "Not found", request=error_response.request, response=error_response
    )
    stub = StubAsyncClient(responses=[error])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: stub)

    client = AsyncHttpClient(error_config=ErrorConfig(strategy=ErrorStrategy.LOG_AND_RETURN_NONE))

    with caplog.at_level(logging.ERROR):
        result = await client.get("http://test.example/api")

    assert result is None
    assert "HTTP GET http://test.example/api failed" in caplog.text


@pytest.mark.asyncio
async def test_async_client_error_strategy_log_and_suppress(monkeypatch, caplog) -> None:
    """AsyncHttpClient with LOG_AND_SUPPRESS logs error and returns None."""
    error_response = _build_response(503, json_data={"error": "unavailable"}, method="POST")
    error = httpx.HTTPStatusError(
        "Unavailable", request=error_response.request, response=error_response
    )
    stub = StubAsyncClient(responses=[error])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: stub)

    client = AsyncHttpClient(error_config=ErrorConfig(strategy=ErrorStrategy.LOG_AND_SUPPRESS))

    with caplog.at_level(logging.ERROR):
        result = await client.post("http://test.example/api", json={})

    assert result is None
    assert "HTTP POST http://test.example/api failed" in caplog.text


@pytest.mark.asyncio
async def test_async_client_no_retry_by_default(monkeypatch) -> None:
    """AsyncHttpClient does not retry by default."""
    error_response = _build_response(500, json_data={"error": "fail"}, method="GET")
    error = httpx.HTTPStatusError(
        "Server error", request=error_response.request, response=error_response
    )
    stub = StubAsyncClient(responses=[error])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: stub)

    client = AsyncHttpClient(error_config=ErrorConfig(strategy=ErrorStrategy.LOG_AND_RETURN_NONE))
    result = await client.get("http://test.example/api")

    assert result is None
    assert stub.call_count == 1  # Only one attempt


@pytest.mark.asyncio
async def test_async_client_retry_on_500_error(monkeypatch) -> None:
    """AsyncHttpClient retries on 500 errors when configured."""
    error_response = _build_response(500, json_data={"error": "fail"}, method="GET")
    error = httpx.HTTPStatusError(
        "Server error", request=error_response.request, response=error_response
    )
    success_response = _build_response(200, json_data={"result": "ok"}, method="GET")

    stub = StubAsyncClient(responses=[error, success_response])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: stub)

    # Mock asyncio.sleep to avoid actual delays
    async def mock_sleep(delay):
        pass

    monkeypatch.setattr(asyncio, "sleep", mock_sleep)

    client = AsyncHttpClient(retry_config=RetryConfig(max_attempts=3, retry_status_codes={500}))
    result = await client.get("http://test.example/api")

    assert result is not None
    assert result.status_code == 200
    assert stub.call_count == 2  # First failed, second succeeded


@pytest.mark.asyncio
async def test_async_client_retry_exhausted(monkeypatch, caplog) -> None:
    """AsyncHttpClient exhausts retries and returns None."""
    error_response = _build_response(503, json_data={"error": "unavailable"}, method="GET")
    error = httpx.HTTPStatusError(
        "Unavailable", request=error_response.request, response=error_response
    )

    # All attempts fail
    stub = StubAsyncClient(responses=[error, error, error])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: stub)

    async def mock_sleep(delay):
        pass

    monkeypatch.setattr(asyncio, "sleep", mock_sleep)

    client = AsyncHttpClient(
        error_config=ErrorConfig(strategy=ErrorStrategy.LOG_AND_RETURN_NONE),
        retry_config=RetryConfig(max_attempts=3, retry_status_codes={503}),
    )

    with caplog.at_level(logging.WARNING):
        result = await client.get("http://test.example/api")

    assert result is None
    assert stub.call_count == 3
    assert "retrying" in caplog.text


@pytest.mark.asyncio
async def test_async_client_no_retry_on_404(monkeypatch) -> None:
    """AsyncHttpClient does not retry on 404 (not in retry_status_codes)."""
    error_response = _build_response(404, json_data={"error": "not found"}, method="GET")
    error = httpx.HTTPStatusError(
        "Not found", request=error_response.request, response=error_response
    )

    stub = StubAsyncClient(responses=[error])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: stub)

    client = AsyncHttpClient(
        error_config=ErrorConfig(strategy=ErrorStrategy.LOG_AND_RETURN_NONE),
        retry_config=RetryConfig(max_attempts=3, retry_status_codes={500, 502, 503}),
    )
    result = await client.get("http://test.example/api")

    assert result is None
    assert stub.call_count == 1  # No retry for 404


@pytest.mark.asyncio
async def test_async_client_retry_on_connect_error(monkeypatch) -> None:
    """AsyncHttpClient retries on connection errors."""
    connect_error = httpx.ConnectError("Connection refused")
    success_response = _build_response(200, json_data={"result": "ok"}, method="GET")

    stub = StubAsyncClient(responses=[connect_error, success_response])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: stub)

    async def mock_sleep(delay):
        pass

    monkeypatch.setattr(asyncio, "sleep", mock_sleep)

    client = AsyncHttpClient(retry_config=RetryConfig(max_attempts=3))
    result = await client.get("http://test.example/api")

    assert result is not None
    assert result.status_code == 200
    assert stub.call_count == 2


# ==================== HttpClient (Sync) Tests ====================


def test_sync_client_default_timeout_from_settings(monkeypatch) -> None:
    """HttpClient uses settings.http.timeout by default."""
    monkeypatch.setattr(settings.http, "timeout", 42, raising=False)
    monkeypatch.setattr(settings.http, "connect_timeout", 7, raising=False)

    client = HttpClient()
    assert client.timeout == 42
    assert client.connect_timeout == 7


def test_sync_client_custom_timeout_override(monkeypatch) -> None:
    """HttpClient accepts custom timeout overrides."""
    monkeypatch.setattr(settings.http, "timeout", 30, raising=False)

    client = HttpClient(timeout=120, connect_timeout=15)
    assert client.timeout == 120
    assert client.connect_timeout == 15


def test_sync_client_get_success(monkeypatch) -> None:
    """HttpClient.get returns response on success."""
    response = _build_response(200, json_data={"result": "ok"}, method="GET")
    stub = StubSyncClient(responses=[response])
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: stub)

    client = HttpClient()
    result = client.get("http://test.example/api")

    assert result is not None
    assert result.status_code == 200
    assert result.json() == {"result": "ok"}


def test_sync_client_post_success(monkeypatch) -> None:
    """HttpClient.post returns response on success."""
    response = _build_response(201, json_data={"created": True}, method="POST")
    stub = StubSyncClient(responses=[response])
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: stub)

    client = HttpClient()
    result = client.post("http://test.example/api", json={"data": "test"})

    assert result is not None
    assert result.status_code == 201
    assert result.json() == {"created": True}


def test_sync_client_error_strategy_raise(monkeypatch) -> None:
    """HttpClient with RAISE strategy re-raises exceptions."""
    error_response = _build_response(500, json_data={"error": "fail"}, method="GET")
    error = httpx.HTTPStatusError(
        "Server error", request=error_response.request, response=error_response
    )
    stub = StubSyncClient(responses=[error])
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: stub)

    client = HttpClient(error_config=ErrorConfig(strategy=ErrorStrategy.RAISE))

    with pytest.raises(httpx.HTTPStatusError):
        client.get("http://test.example/api")


def test_sync_client_error_strategy_log_and_return_none(monkeypatch, caplog) -> None:
    """HttpClient with LOG_AND_RETURN_NONE logs error and returns None."""
    error_response = _build_response(404, json_data={"error": "not found"}, method="GET")
    error = httpx.HTTPStatusError(
        "Not found", request=error_response.request, response=error_response
    )
    stub = StubSyncClient(responses=[error])
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: stub)

    client = HttpClient(error_config=ErrorConfig(strategy=ErrorStrategy.LOG_AND_RETURN_NONE))

    with caplog.at_level(logging.ERROR):
        result = client.get("http://test.example/api")

    assert result is None
    assert "HTTP GET http://test.example/api failed" in caplog.text


def test_sync_client_retry_on_500_error(monkeypatch) -> None:
    """HttpClient retries on 500 errors when configured."""
    error_response = _build_response(500, json_data={"error": "fail"}, method="GET")
    error = httpx.HTTPStatusError(
        "Server error", request=error_response.request, response=error_response
    )
    success_response = _build_response(200, json_data={"result": "ok"}, method="GET")

    stub = StubSyncClient(responses=[error, success_response])
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: stub)

    # Mock time.sleep to avoid actual delays
    def mock_sleep(delay):
        pass

    monkeypatch.setattr(time, "sleep", mock_sleep)

    client = HttpClient(retry_config=RetryConfig(max_attempts=3, retry_status_codes={500}))
    result = client.get("http://test.example/api")

    assert result is not None
    assert result.status_code == 200
    assert stub.call_count == 2  # First failed, second succeeded


def test_sync_client_retry_exhausted(monkeypatch, caplog) -> None:
    """HttpClient exhausts retries and returns None."""
    error_response = _build_response(503, json_data={"error": "unavailable"}, method="GET")
    error = httpx.HTTPStatusError(
        "Unavailable", request=error_response.request, response=error_response
    )

    # All attempts fail
    stub = StubSyncClient(responses=[error, error, error])
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: stub)

    def mock_sleep(delay):
        pass

    monkeypatch.setattr(time, "sleep", mock_sleep)

    client = HttpClient(
        error_config=ErrorConfig(strategy=ErrorStrategy.LOG_AND_RETURN_NONE),
        retry_config=RetryConfig(max_attempts=3, retry_status_codes={503}),
    )

    with caplog.at_level(logging.WARNING):
        result = client.get("http://test.example/api")

    assert result is None
    assert stub.call_count == 3
    assert "retrying" in caplog.text
