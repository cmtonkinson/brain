"""Real-provider integration tests for Qdrant substrate behavior."""

from __future__ import annotations

from uuid import uuid4

import pytest

from packages.brain_shared.config import load_settings, resolve_component_settings
from resources.substrates.qdrant.component import RESOURCE_COMPONENT_ID
from resources.substrates.qdrant.config import QdrantConfig, QdrantSettings
from resources.substrates.qdrant.qdrant_substrate import QdrantClientSubstrate
from tests.integration.helpers import real_provider_tests_enabled


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def test_upsert_search_delete_roundtrip() -> None:
    """Qdrant substrate should upsert/search/delete one point in unique collection."""
    settings = resolve_component_settings(
        settings=load_settings(),
        component_id=str(RESOURCE_COMPONENT_ID),
        model=QdrantSettings,
    )
    collection = f"int_qdrant_{uuid4().hex[:8]}"
    config = QdrantConfig(
        url=settings.url,
        timeout_seconds=settings.request_timeout_seconds,
        collection_name=collection,
        distance_metric=settings.distance_metric,
    )
    substrate = QdrantClientSubstrate(config)

    substrate.upsert_point(
        point_id="chunk-1",
        vector=[0.1, 0.2],
        payload={"source_id": "src-1", "chunk_id": "chunk-1"},
    )
    hits = substrate.search_points(
        filters={"source_id": "src-1"},
        query_vector=[0.1, 0.2],
        limit=5,
    )

    assert len(hits) >= 1
    assert substrate.delete_point(point_id="chunk-1") is True
