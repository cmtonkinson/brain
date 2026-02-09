"""Unit tests for Letta service parsing and fallbacks."""

from __future__ import annotations

import httpx
import pytest

from services.letta import LettaService


def _build_response(
    status_code: int,
    *,
    json_data: object | None = None,
    content: str | bytes | None = None,
    method: str = "GET",
    url: str = "http://letta.test",
) -> httpx.Response:
    """Create a synthetic httpx response with a bound request."""
    request = httpx.Request(method, url)
    return httpx.Response(status_code=status_code, json=json_data, content=content, request=request)


class StubSyncClient:
    """Synchronous client stub returning configured responses."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        """Initialize the stub with a sequence of responses."""
        self.responses = responses
        self.call_count = 0

    def __enter__(self) -> "StubSyncClient":
        """Enter the context manager."""
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Exit the context manager."""
        pass

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Return the next configured response."""
        if self.call_count >= len(self.responses):
            return _build_response(200, json_data={}, method=method, url=url)
        response = self.responses[self.call_count]
        self.call_count += 1
        return response


def test_post_with_fallbacks_skips_unavailable(monkeypatch) -> None:
    """POST fallback continues after 404/422 and returns first valid JSON."""
    service = LettaService()
    responses = [
        _build_response(404, content="missing", method="POST"),
        _build_response(200, json_data={"ok": True}, method="POST"),
    ]
    stub = StubSyncClient(responses)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: stub)

    data = service._post_with_fallbacks([("http://letta.test/a", {}), ("http://letta.test/b", {})])

    assert data == {"ok": True}


def test_post_with_fallbacks_raises_after_exhaustion(monkeypatch) -> None:
    """POST fallback raises a RuntimeError after all endpoints fail."""
    service = LettaService()
    responses = [
        _build_response(404, content="missing", method="POST"),
        _build_response(422, content="invalid", method="POST"),
    ]
    stub = StubSyncClient(responses)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: stub)

    with pytest.raises(RuntimeError, match="last status=422"):
        service._post_with_fallbacks([("http://letta.test/a", {}), ("http://letta.test/b", {})])


def test_get_with_fallbacks_skips_unavailable(monkeypatch) -> None:
    """GET fallback continues after 404/422 and returns the first valid JSON."""
    service = LettaService()
    responses = [
        _build_response(422, content="invalid", method="GET"),
        _build_response(200, json_data={"items": []}, method="GET"),
    ]
    stub = StubSyncClient(responses)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: stub)

    data = service._get_with_fallbacks([("http://letta.test/a", {}), ("http://letta.test/b", {})])

    assert data == {"items": []}
