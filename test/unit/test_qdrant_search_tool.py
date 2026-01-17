"""Unit tests for the Letta Qdrant search tool."""

from __future__ import annotations

import httpx

from config import settings
from letta_tools import qdrant_search


def _build_response(
    status_code: int,
    *,
    json_data: object | None = None,
    content: str | bytes | None = None,
    method: str = "POST",
    url: str = "http://embeddings.test",
) -> httpx.Response:
    """Create a synthetic httpx response with a bound request."""
    request = httpx.Request(method, url)
    return httpx.Response(status_code=status_code, json=json_data, content=content, request=request)


class DummyPoint:
    """Minimal Qdrant point stub."""

    def __init__(self, score: float, payload: dict[str, object]) -> None:
        """Initialize with a score and payload."""
        self.score = score
        self.payload = payload


class DummyResults:
    """Minimal Qdrant results stub."""

    def __init__(self, points: list[DummyPoint]) -> None:
        """Initialize with a list of points."""
        self.points = points


class DummyQdrantClient:
    """Qdrant client stub returning configured points."""

    def __init__(self, url: str) -> None:
        """Initialize with a URL."""
        self.url = url

    def query_points(self, **kwargs) -> DummyResults:
        """Return a stubbed result set."""
        points = kwargs.get("points_override")
        if points is None:
            points = []
        return DummyResults(points)


def test_search_vault_returns_no_results(monkeypatch) -> None:
    """search_vault returns a friendly message when empty."""
    monkeypatch.setattr(settings.llm, "embed_base_url", "http://embeddings.test", raising=False)
    monkeypatch.setattr(settings.qdrant, "url", "http://qdrant.test", raising=False)
    monkeypatch.setattr(settings.indexer, "collection", "obsidian", raising=False)
    response = _build_response(200, json_data={"embedding": [0.1, 0.2, 0.3]})

    def _fake_post(*args, **kwargs) -> httpx.Response:
        return response

    monkeypatch.setattr(httpx, "post", _fake_post)
    monkeypatch.setattr(qdrant_search, "QdrantClient", DummyQdrantClient)

    result = qdrant_search.search_vault("query", limit=2)

    assert result == "No results found."


def test_search_vault_truncates_snippet(monkeypatch) -> None:
    """search_vault truncates long snippets."""
    monkeypatch.setattr(settings.llm, "embed_base_url", "http://embeddings.test", raising=False)
    monkeypatch.setattr(settings.qdrant, "url", "http://qdrant.test", raising=False)
    monkeypatch.setattr(settings.indexer, "collection", "obsidian", raising=False)
    response = _build_response(200, json_data={"embedding": [0.1, 0.2, 0.3]})

    def _fake_post(*args, **kwargs) -> httpx.Response:
        return response

    monkeypatch.setattr(httpx, "post", _fake_post)

    class DummyQdrantClientWithPoints(DummyQdrantClient):
        """Qdrant client stub returning a long snippet."""

        def query_points(self, **kwargs) -> DummyResults:
            text = "word " * 100
            points = [DummyPoint(0.9, {"path": "note.md", "text": text})]
            return DummyResults(points)

    monkeypatch.setattr(qdrant_search, "QdrantClient", DummyQdrantClientWithPoints)

    result = qdrant_search.search_vault("query", limit=1)

    assert "note.md" in result
    assert "..." in result
