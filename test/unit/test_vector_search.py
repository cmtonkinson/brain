"""Unit tests for vector search helpers."""

from __future__ import annotations

import httpx
import pytest

from config import settings
from services import vector_search


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
    """Qdrant client stub capturing query inputs."""

    def __init__(self, url: str) -> None:
        """Initialize with a URL."""
        self.url = url
        self.last_query = None

    def query_points(self, **kwargs) -> DummyResults:
        """Return a stubbed result set."""
        self.last_query = kwargs
        points = [
            DummyPoint(0.9, {"path": "a.md", "text": "alpha"}),
            DummyPoint(0.8, {"path": "b.md", "text": "beta"}),
        ]
        return DummyResults(points)


def test_embed_query_raises_on_missing_embedding(monkeypatch) -> None:
    """_embed_query raises when embeddings payload is missing."""
    response = _build_response(200, json_data={"unexpected": "shape"})

    def _fake_post(*args, **kwargs) -> httpx.Response:
        return response

    monkeypatch.setattr(httpx, "post", _fake_post)

    with pytest.raises(ValueError, match="missing 'embedding'"):
        vector_search._embed_query("query")


def test_search_vault_formats_results(monkeypatch) -> None:
    """search_vault formats Qdrant results into dicts."""
    monkeypatch.setattr(settings.llm, "embed_base_url", "http://embeddings.test", raising=False)
    monkeypatch.setattr(settings.qdrant, "url", "http://qdrant.test", raising=False)
    monkeypatch.setattr(settings.indexer, "collection", "obsidian", raising=False)
    response = _build_response(200, json_data={"embedding": [0.1, 0.2, 0.3]})

    def _fake_post(*args, **kwargs) -> httpx.Response:
        return response

    monkeypatch.setattr(httpx, "post", _fake_post)
    monkeypatch.setattr(vector_search, "QdrantClient", DummyQdrantClient)

    results = vector_search.search_vault("query", limit=2, collection="obsidian")

    assert results == [
        {"path": "a.md", "score": 0.9, "text": "alpha"},
        {"path": "b.md", "score": 0.8, "text": "beta"},
    ]
