"""Unit tests for the Signal client integration."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from config import settings
from services.signal import SignalClient


def _build_response(
    status_code: int,
    *,
    json_data: object | None = None,
    content: str | bytes | None = None,
    method: str = "GET",
    url: str = "http://signal.test",
) -> httpx.Response:
    """Create a synthetic httpx response with a bound request."""
    request = httpx.Request(method, url)
    return httpx.Response(status_code=status_code, json=json_data, content=content, request=request)


class StubAsyncClient:
    """Async client stub returning configured responses."""

    def __init__(self, *, get=None, post=None) -> None:
        """Initialize the stub with optional responses or exceptions."""
        self._get = get
        self._post = post

    async def __aenter__(self) -> "StubAsyncClient":
        """Enter the async context manager."""
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        """Exit the async context manager."""
        return False

    async def get(self, url: str, **kwargs) -> httpx.Response:
        """Return the configured GET response or raise the configured error."""
        if isinstance(self._get, Exception):
            raise self._get
        response = self._get or _build_response(200, json_data=[], method="GET", url=url)
        response.request = httpx.Request("GET", url)
        return response

    async def post(self, url: str, **kwargs) -> httpx.Response:
        """Return the configured POST response or raise the configured error."""
        if isinstance(self._post, Exception):
            raise self._post
        response = self._post or _build_response(200, json_data={}, method="POST", url=url)
        response.request = httpx.Request("POST", url)
        return response


@pytest.mark.asyncio
async def test_poll_messages_filters_and_parses(monkeypatch) -> None:
    """poll_messages ignores non-data and empty messages, returning parsed entries."""
    monkeypatch.setattr(settings.signal, "url", "http://signal.test", raising=False)
    payload = [
        {"envelope": {"dataMessage": None}},
        {"envelope": {"dataMessage": {"message": ""}}},
        {
            "envelope": {
                "source": "+15550001111",
                "sourceDevice": 2,
                "dataMessage": {
                    "message": "hello",
                    "timestamp": 1_700_000_000_000,
                    "expiresInSeconds": 12,
                },
            }
        },
        {
            "envelope": {
                "source": "+15550002222",
                "dataMessage": {"message": "world", "timestamp": 0},
            }
        },
    ]
    response = _build_response(200, json_data=payload, method="GET")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: StubAsyncClient(get=response))

    client = SignalClient(api_url="http://signal.test")
    messages = await client.poll_messages("+15550001111")

    assert len(messages) == 2
    assert messages[0].sender == "+15550001111"
    assert messages[0].source_device == 2
    assert messages[0].expires_in_seconds == 12
    assert messages[0].timestamp == datetime.fromtimestamp(1_700_000_000)
    assert messages[1].sender == "+15550002222"
    assert messages[1].source_device == 1
    assert messages[1].expires_in_seconds == 0


@pytest.mark.asyncio
async def test_poll_messages_handles_http_error(monkeypatch) -> None:
    """poll_messages returns an empty list on HTTP status errors."""
    monkeypatch.setattr(settings.signal, "url", "http://signal.test", raising=False)
    response = _build_response(500, json_data={"error": "fail"}, method="GET")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: StubAsyncClient(get=response))

    client = SignalClient(api_url="http://signal.test")
    messages = await client.poll_messages("+15550001111")

    assert messages == []


@pytest.mark.asyncio
async def test_send_message_returns_false_on_error(monkeypatch) -> None:
    """send_message returns False when the API responds with an error."""
    monkeypatch.setattr(settings.signal, "url", "http://signal.test", raising=False)
    response = _build_response(500, json_data={"error": "fail"}, method="POST")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: StubAsyncClient(post=response))

    client = SignalClient(api_url="http://signal.test")
    ok = await client.send_message("+15550001111", "+15550002222", "hi")

    assert ok is False
