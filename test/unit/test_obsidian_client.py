"""Unit tests for the Obsidian REST client."""

from __future__ import annotations

import httpx
import pytest

from config import settings
from tools.obsidian import ObsidianClient


def _build_response(
    status_code: int,
    *,
    json_data: object | None = None,
    content: str | bytes | None = None,
    method: str = "GET",
    url: str = "http://obsidian.test",
) -> httpx.Response:
    """Create a synthetic httpx response with a bound request."""
    request = httpx.Request(method, url)
    return httpx.Response(status_code=status_code, json=json_data, content=content, request=request)


class StubAsyncClient:
    """Async client stub that returns preconfigured responses."""

    def __init__(self, *, get=None, post=None, put=None) -> None:
        """Initialize the stub with optional responses or exceptions."""
        self._get = get
        self._post = post
        self._put = put

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
        response = self._post or _build_response(200, json_data=[], method="POST", url=url)
        response.request = httpx.Request("POST", url)
        return response

    async def put(self, url: str, **kwargs) -> httpx.Response:
        """Return the configured PUT response or raise the configured error."""
        if isinstance(self._put, Exception):
            raise self._put
        response = self._put or _build_response(200, json_data={}, method="PUT", url=url)
        response.request = httpx.Request("PUT", url)
        return response


@pytest.mark.asyncio
async def test_search_parses_dict_results(monkeypatch) -> None:
    """Search returns a sliced list when the API responds with a dict."""
    monkeypatch.setattr(settings.obsidian, "url", "http://obsidian.test", raising=False)
    results = [{"path": "a.md"}, {"path": "b.md"}, {"path": "c.md"}]
    response = _build_response(200, json_data={"results": results}, method="POST")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: StubAsyncClient(post=response))

    client = ObsidianClient()
    data = await client.search("query", limit=2)

    assert data == results[:2]


@pytest.mark.asyncio
async def test_get_note_404_raises_file_not_found(monkeypatch) -> None:
    """get_note converts 404 responses into FileNotFoundError."""
    monkeypatch.setattr(settings.obsidian, "url", "http://obsidian.test", raising=False)
    response = _build_response(404, content="missing", method="GET")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: StubAsyncClient(get=response))

    client = ObsidianClient()

    with pytest.raises(FileNotFoundError, match="Note not found"):
        await client.get_note("missing.md")


@pytest.mark.asyncio
async def test_append_note_404_raises_file_not_found(monkeypatch) -> None:
    """append_to_note converts 404 responses into FileNotFoundError."""
    monkeypatch.setattr(settings.obsidian, "url", "http://obsidian.test", raising=False)
    response = _build_response(404, content="missing", method="POST")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: StubAsyncClient(post=response))

    client = ObsidianClient()

    with pytest.raises(FileNotFoundError, match="Note not found"):
        await client.append_to_note("missing.md", "content")


@pytest.mark.asyncio
async def test_list_dir_non_json_raises(monkeypatch) -> None:
    """list_dir raises when the API returns non-JSON data."""
    monkeypatch.setattr(settings.obsidian, "url", "http://obsidian.test", raising=False)
    response = _build_response(200, content="not-json", method="GET")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: StubAsyncClient(get=response))

    client = ObsidianClient()

    with pytest.raises(ValueError, match="non-JSON"):
        await client.list_dir("Notes")


@pytest.mark.asyncio
async def test_list_dir_unexpected_shape_raises(monkeypatch) -> None:
    """list_dir raises when the API returns an unexpected JSON shape."""
    monkeypatch.setattr(settings.obsidian, "url", "http://obsidian.test", raising=False)
    response = _build_response(200, json_data={"unexpected": "shape"}, method="GET")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: StubAsyncClient(get=response))

    client = ObsidianClient()

    with pytest.raises(ValueError, match="unexpected response shape"):
        await client.list_dir("Notes")
