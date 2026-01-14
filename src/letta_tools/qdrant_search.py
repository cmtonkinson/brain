"""Letta tool: semantic search over vault embeddings stored in Qdrant."""

from __future__ import annotations

import os

import httpx
from qdrant_client import QdrantClient


def _embed_query(text: str) -> list[float]:
    base_url = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
    model = os.environ.get("OLLAMA_EMBED_MODEL", "mxbai-embed-large")
    response = httpx.post(
        f"{base_url.rstrip('/')}/api/embeddings",
        json={"model": model, "prompt": text},
        timeout=60.0,
    )
    response.raise_for_status()
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
    qdrant_url = os.environ.get("QDRANT_URL", "http://qdrant:6333")
    collection = os.environ.get("INDEXER_COLLECTION", "obsidian")

    vector = _embed_query(query)
    qdrant = QdrantClient(url=qdrant_url)
    results = qdrant.search(
        collection_name=collection,
        query_vector=vector,
        limit=limit,
    )

    if not results:
        return "No results found."

    lines = []
    for idx, hit in enumerate(results, 1):
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
