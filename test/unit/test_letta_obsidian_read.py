"""Unit tests for Letta Obsidian read tool."""

from __future__ import annotations

import httpx
import pytest

from config import settings
from letta_tools import obsidian_read


def _build_response(
    status_code: int,
    *,
    content: str | bytes | None = None,
    method: str = "GET",
    url: str = "http://obsidian.test",
) -> httpx.Response:
    """Create a synthetic httpx response with a bound request."""
    request = httpx.Request(method, url)
    return httpx.Response(status_code=status_code, content=content, request=request)


class StubSyncClient:
    """Synchronous client stub returning configured response."""

    def __init__(self, response: httpx.Response) -> None:
        """Initialize the stub with a response."""
        self.response = response

    def __enter__(self) -> "StubSyncClient":
        """Enter the context manager."""
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Exit the context manager."""
        pass

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Return the configured response."""
        return self.response


def test_read_note_requires_api_key(monkeypatch) -> None:
    """read_note raises when the API key is missing."""
    monkeypatch.setattr(settings.obsidian, "api_key", None, raising=False)

    with pytest.raises(ValueError, match="OBSIDIAN_API_KEY"):
        obsidian_read.read_note("note.md")


def test_read_note_returns_not_found_message(monkeypatch) -> None:
    """read_note returns a friendly message on 404 responses."""
    monkeypatch.setattr(settings.obsidian, "api_key", "test-key", raising=False)
    response = _build_response(404, content="missing")
    stub = StubSyncClient(response)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: stub)

    result = obsidian_read.read_note("missing.md")

    assert result == "Note not found: missing.md"


def test_read_note_truncates_long_content(monkeypatch) -> None:
    """read_note truncates content exceeding max_chars."""
    monkeypatch.setattr(settings.obsidian, "api_key", "test-key", raising=False)
    long_text = "A" * 20
    response = _build_response(200, content=long_text)
    stub = StubSyncClient(response)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: stub)

    result = obsidian_read.read_note("note.md", max_chars=10)

    assert result.startswith("A" * 10)
    assert result.endswith("... (note truncated)")
