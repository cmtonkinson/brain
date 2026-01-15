"""Vector search helpers for Qdrant-backed embeddings."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from qdrant_client import QdrantClient

from config import settings

logger = logging.getLogger(__name__)


def _embed_query(text: str) -> list[float]:
    response = httpx.post(
        f"{settings.ollama_url.rstrip('/')}/api/embeddings",
        json={"model": settings.ollama_embed_model, "prompt": text},
        timeout=60.0,
    )
    response.raise_for_status()
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
    collection = collection or settings.indexer_collection
    logger.info("vector_search: query=%r limit=%s collection=%s", query, limit, collection)
    qdrant = QdrantClient(url=settings.qdrant_url)
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
