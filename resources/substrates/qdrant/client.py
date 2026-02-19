"""Qdrant client construction helpers."""

from __future__ import annotations

from qdrant_client import QdrantClient

from resources.substrates.qdrant.config import QdrantConfig


def create_qdrant_client(config: QdrantConfig) -> QdrantClient:
    """Construct a configured Qdrant client instance."""
    config.validate()
    return QdrantClient(url=config.url, timeout=config.timeout_seconds)
