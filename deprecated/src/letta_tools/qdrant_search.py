"""Letta tool: semantic search over vault embeddings stored in Qdrant."""

from __future__ import annotations

from qdrant_client import QdrantClient

from config import settings
from services.http_client import HttpClient


def _embed_query(text: str) -> list[float]:
    """Embed a search query using the configured embedding endpoint."""
    base_url = settings.llm.embed_base_url
    model = settings.llm.embed_model
    client = HttpClient(timeout=settings.llm.timeout)
    response = client.post(
        f"{base_url.rstrip('/')}/api/embeddings",
        json={"model": model, "prompt": text},
    )
    payload = response.json()
    embedding = payload.get("embedding")
    if not embedding:
        raise ValueError("Ollama embeddings response missing 'embedding'.")
    return embedding


def search_vault(query: str, limit: int = 8) -> str:
    """Search the vault embeddings for the given query.

    Args:
        query: Natural language query to embed and search.
        limit: Maximum number of results to return.
    """
    qdrant_url = settings.qdrant.url
    collection = settings.indexer.collection

    vector = _embed_query(query)
    qdrant = QdrantClient(url=qdrant_url)
    results = qdrant.query_points(
        collection_name=collection,
        query=vector,
        limit=limit,
        with_payload=True,
    )

    if not results.points:
        return "No results found."

    lines = []
    for idx, hit in enumerate(results.points, 1):
        payload = hit.payload or {}
        path = payload.get("path") or "Unknown"
        text = (payload.get("text") or "").strip()
        snippet = " ".join(text.split())
        if len(snippet) > 240:
            snippet = snippet[:240] + "..."
        lines.append(f"{idx}. {path} (score {hit.score:.3f})")
        if snippet:
            lines.append(f"   {snippet}")

    return "\n".join(lines)
