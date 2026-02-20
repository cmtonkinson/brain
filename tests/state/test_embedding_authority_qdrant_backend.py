"""Unit tests for EAS Qdrant backend collection/bootstrap behavior."""

from __future__ import annotations

import pytest

import services.state.embedding_authority.qdrant_backend as qdrant_backend_module
from services.state.embedding_authority.qdrant_backend import QdrantEmbeddingBackend


class _FakeSubstrate:
    """In-memory substrate fake for backend behavior tests."""

    def __init__(self, config: object) -> None:
        self.config = config
        self.size: int | None = None
        self.points: dict[str, tuple[tuple[float, ...], dict[str, object]]] = {}

    def get_collection_vector_size(self) -> int | None:
        return self.size

    def upsert_point(
        self,
        *,
        point_id: str,
        vector: list[float] | tuple[float, ...],
        payload: dict[str, object],
    ) -> None:
        if self.size is None:
            self.size = len(vector)
        self.points[point_id] = (tuple(float(value) for value in vector), dict(payload))

    def retrieve_point(self, *, point_id: str) -> object | None:
        row = self.points.get(point_id)
        if row is None:
            return None

        class _Point:
            def __init__(
                self, vector: tuple[float, ...], payload: dict[str, object]
            ) -> None:
                self.vector = vector
                self.payload = payload

        return _Point(vector=row[0], payload=row[1])

    def delete_point(self, *, point_id: str) -> bool:
        existed = point_id in self.points
        self.points.pop(point_id, None)
        return existed


def test_ensure_collection_bootstraps_missing_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing collections should be created via temporary bootstrap point."""
    monkeypatch.setattr(qdrant_backend_module, "QdrantClientSubstrate", _FakeSubstrate)

    backend = QdrantEmbeddingBackend(
        qdrant_url="http://qdrant:6333",
        request_timeout_seconds=5.0,
        distance_metric="cosine",
    )
    backend.ensure_collection(spec_id="spec_a", dimensions=8)

    substrate = backend._substrates["spec_a"]
    assert isinstance(substrate, _FakeSubstrate)
    assert substrate.size == 8
    assert "__bootstrap__" not in substrate.points


def test_ensure_collection_raises_on_dimension_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing collections with wrong dimensions must fail loudly."""
    monkeypatch.setattr(qdrant_backend_module, "QdrantClientSubstrate", _FakeSubstrate)

    backend = QdrantEmbeddingBackend(
        qdrant_url="http://qdrant:6333",
        request_timeout_seconds=5.0,
        distance_metric="cosine",
    )
    backend.ensure_collection(spec_id="spec_b", dimensions=4)

    substrate = backend._substrates["spec_b"]
    assert isinstance(substrate, _FakeSubstrate)
    substrate.size = 9

    with pytest.raises(ValueError, match="dimension mismatch"):
        backend.ensure_collection(spec_id="spec_b", dimensions=4)


def test_point_operations_are_scoped_by_spec_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Point upsert/delete/existence checks should be isolated per spec collection."""
    monkeypatch.setattr(qdrant_backend_module, "QdrantClientSubstrate", _FakeSubstrate)

    backend = QdrantEmbeddingBackend(
        qdrant_url="http://qdrant:6333",
        request_timeout_seconds=5.0,
        distance_metric="cosine",
    )

    backend.upsert_point(
        spec_id="spec_x",
        chunk_id="chunk_1",
        vector=(0.1, 0.2),
        payload={"source_id": "src"},
    )

    assert backend.point_exists(spec_id="spec_x", chunk_id="chunk_1") is True
    assert backend.point_exists(spec_id="spec_y", chunk_id="chunk_1") is False

    assert backend.delete_point(spec_id="spec_x", chunk_id="chunk_1") is True
    assert backend.point_exists(spec_id="spec_x", chunk_id="chunk_1") is False
