"""Unit tests for Qdrant substrate configuration validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from resources.substrates.qdrant.config import QdrantConfig


def test_qdrant_config_rejects_invalid_distance_metric() -> None:
    """Qdrant config should reject unsupported distance metrics."""
    with pytest.raises(ValidationError, match="qdrant.distance_metric must be one of"):
        QdrantConfig(
            url="http://qdrant:6333",
            timeout_seconds=5.0,
            collection_name="spec_a",
            distance_metric="manhattan",
        )


def test_qdrant_config_rejects_missing_required_fields() -> None:
    """Qdrant config should reject empty url/collection and nonpositive timeout."""
    with pytest.raises(ValidationError, match="qdrant.url is required"):
        QdrantConfig(
            url="",
            timeout_seconds=5.0,
            collection_name="spec_a",
            distance_metric="cosine",
        )

    with pytest.raises(ValidationError, match="qdrant.timeout_seconds must be > 0"):
        QdrantConfig(
            url="http://qdrant:6333",
            timeout_seconds=0.0,
            collection_name="spec_a",
            distance_metric="cosine",
        )

    with pytest.raises(ValidationError, match="qdrant.collection_name is required"):
        QdrantConfig(
            url="http://qdrant:6333",
            timeout_seconds=5.0,
            collection_name="",
            distance_metric="cosine",
        )
