"""Vector search helpers for Qdrant-backed embeddings."""

from __future__ import annotations

import logging
from typing import Any

from qdrant_client import QdrantClient

from config import settings
from services.http_client import HttpClient

logger = logging.getLogger(__name__)


def _embed_query(text: str) -> list[float]:
    """Embed a query string using the configured embedding endpoint."""
    client = HttpClient(timeout=settings.llm.timeout)
    response = client.post(
        f"{settings.llm.embed_base_url.rstrip('/')}/api/embeddings",
        json={"model": settings.llm.embed_model, "prompt": text},
    )
    payload = response.json()
    embedding = payload.get("embedding")
    if not embedding:
        raise ValueError("Ollama embeddings response missing 'embedding'.")
    return embedding


def search_vault(
    query: str,
    limit: int = 8,
    collection: str | None = None,
) -> list[dict[str, Any]]:
    """Search the Qdrant collection for similar embeddings."""
    collection = collection or settings.indexer.collection
    logger.info("vector_search: query=%r limit=%s collection=%s", query, limit, collection)
    qdrant = QdrantClient(url=settings.qdrant.url)
    vector = _embed_query(query)
    results = qdrant.query_points(
        collection_name=collection,
        query=vector,
        limit=limit,
        with_payload=True,
    )

    formatted: list[dict[str, Any]] = []
    for hit in results.points:
        payload = hit.payload or {}
        formatted.append(
            {
                "path": payload.get("path"),
                "score": hit.score,
                "text": payload.get("text"),
            }
        )
    logger.info("vector_search: %s result(s)", len(formatted))
    return formatted
