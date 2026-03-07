"""Real-provider integration tests for Qdrant substrate behavior."""

from __future__ import annotations

import pytest

from packages.brain_shared.ids import generate_ulid_str
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
    collection = f"int_qdrant_{generate_ulid_str().lower()}"
    point_id = generate_ulid_str()
    config = QdrantConfig(
        url=qdrant_url,
        timeout_seconds=3.0,
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
