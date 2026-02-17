"""Integration test against a live Qdrant instance (optional)."""

from __future__ import annotations

import uuid

import pytest

from config import settings
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels


@pytest.mark.integration
def test_qdrant_happy_path_collection_round_trip() -> None:
    """Create, upsert, search, and delete a collection."""
    if not settings.qdrant.url:
        raise AssertionError("QDRANT_URL is required for Qdrant integration tests.")

    client = QdrantClient(url=settings.qdrant.url)
    client.get_collections()

    collection = f"brain-test-{uuid.uuid4().hex[:8]}"
    try:
        client.create_collection(
            collection_name=collection,
            vectors_config=qmodels.VectorParams(size=3, distance=qmodels.Distance.COSINE),
        )

        point_id = uuid.uuid4().hex
        client.upsert(
            collection_name=collection,
            points=[
                qmodels.PointStruct(
                    id=point_id,
                    vector=[0.1, 0.2, 0.3],
                    payload={"path": "Notes/Test.md"},
                )
            ],
        )

        results = client.query_points(
            collection_name=collection,
            query=[0.1, 0.2, 0.3],
            limit=1,
        )

        assert results.points
        assert results.points[0].payload.get("path") == "Notes/Test.md"
    finally:
        client.delete_collection(collection_name=collection)
