"""Unit tests for direct Qdrant substrate delete semantics."""

from __future__ import annotations

import resources.substrates.qdrant.qdrant_substrate as substrate_module
from resources.substrates.qdrant.config import QdrantConfig
from resources.substrates.qdrant.qdrant_substrate import QdrantClientSubstrate


class _FakeDeleteClient:
    """Minimal Qdrant client fake focused on delete-point behavior."""

    def __init__(self, *, collection_exists: bool) -> None:
        self._collection_exists = collection_exists
        self.delete_calls = 0
        self.retrieve_calls = 0

    def collection_exists(self, _: str) -> bool:
        return self._collection_exists

    def delete(self, **_: object) -> None:
        self.delete_calls += 1

    def retrieve(self, **_: object) -> list[object]:
        self.retrieve_calls += 1
        return []


def _config() -> QdrantConfig:
    """Build valid substrate configuration for test construction."""
    return QdrantConfig(
        url="http://qdrant:6333",
        timeout_seconds=5.0,
        collection_name="spec_test",
        distance_metric="cosine",
    )


def test_delete_point_is_single_call_and_idempotent(
    monkeypatch: object,
) -> None:
    """Delete should issue one delete request without a pre-retrieve existence call."""
    fake_client = _FakeDeleteClient(collection_exists=True)
    monkeypatch.setattr(
        substrate_module,
        "create_qdrant_client",
        lambda _: fake_client,
    )
    substrate = QdrantClientSubstrate(_config())

    deleted = substrate.delete_point(point_id="chunk_1")

    assert deleted is True
    assert fake_client.delete_calls == 1
    assert fake_client.retrieve_calls == 0


def test_delete_point_noops_when_collection_missing(monkeypatch: object) -> None:
    """Delete should return False and avoid Qdrant delete when collection is missing."""
    fake_client = _FakeDeleteClient(collection_exists=False)
    monkeypatch.setattr(
        substrate_module,
        "create_qdrant_client",
        lambda _: fake_client,
    )
    substrate = QdrantClientSubstrate(_config())

    deleted = substrate.delete_point(point_id="chunk_1")

    assert deleted is False
    assert fake_client.delete_calls == 0
    assert fake_client.retrieve_calls == 0
