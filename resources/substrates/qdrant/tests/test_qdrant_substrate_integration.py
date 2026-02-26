"""Real-provider integration tests for Qdrant substrate behavior."""

from __future__ import annotations

from uuid import uuid4

import pytest

from resources.substrates.qdrant.config import QdrantConfig
from resources.substrates.qdrant.qdrant_substrate import QdrantClientSubstrate
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def test_upsert_search_delete_roundtrip(qdrant_url: str) -> None:
    """Qdrant substrate should upsert/search/delete one point in unique collection."""
    collection = f"int_qdrant_{uuid4().hex[:8]}"
    point_id = str(uuid4())
    config = QdrantConfig(
        url=qdrant_url,
        timeout_seconds=1.0,
        collection_name=collection,
        distance_metric="cosine",
    )
    substrate = QdrantClientSubstrate(config)

    substrate.upsert_point(
        point_id=point_id,
        vector=[0.1, 0.2],
        payload={"source_id": "src-1", "chunk_id": point_id},
    )
    hits = substrate.search_points(
        filters={"source_id": "src-1"},
        query_vector=[0.1, 0.2],
        limit=5,
    )

    assert len(hits) >= 1
    assert substrate.delete_point(point_id=point_id) is True
