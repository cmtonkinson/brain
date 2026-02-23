"""Unit tests for EAS Qdrant backend collection/bootstrap behavior."""

from __future__ import annotations

import pytest

from resources.substrates.qdrant.config import QdrantSettings
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

    def search_points(
        self,
        *,
        filters: dict[str, str],
        query_vector: list[float] | tuple[float, ...],
        limit: int,
    ) -> list[object]:
        del query_vector

        class _SearchPoint:
            def __init__(self, score: float, payload: dict[str, object]) -> None:
                self.score = score
                self.payload = payload

        results: list[object] = []
        for _, (_, payload) in sorted(self.points.items()):
            if filters and any(
                payload.get(key) != value for key, value in filters.items()
            ):
                continue
            results.append(_SearchPoint(score=1.0, payload=dict(payload)))
            if len(results) >= limit:
                break
        return results


def _qdrant_settings() -> QdrantSettings:
    return QdrantSettings(
        url="http://qdrant:6333",
        request_timeout_seconds=5.0,
        distance_metric="cosine",
    )


def test_ensure_collection_bootstraps_missing_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing collections should be created via temporary bootstrap point."""
    monkeypatch.setattr(qdrant_backend_module, "QdrantClientSubstrate", _FakeSubstrate)

    backend = QdrantEmbeddingBackend(settings=_qdrant_settings())
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

    backend = QdrantEmbeddingBackend(settings=_qdrant_settings())
    backend.ensure_collection(spec_id="spec_b", dimensions=4)

    substrate = backend._substrates["spec_b"]
    assert isinstance(substrate, _FakeSubstrate)
    substrate.size = 9

    with pytest.raises(ValueError, match="dimension mismatch"):
        backend.ensure_collection(spec_id="spec_b", dimensions=4)


def test_point_operations_are_scoped_by_spec_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Point upsert/delete operations should be isolated per spec collection."""
    monkeypatch.setattr(qdrant_backend_module, "QdrantClientSubstrate", _FakeSubstrate)

    backend = QdrantEmbeddingBackend(settings=_qdrant_settings())

    backend.upsert_point(
        spec_id="spec_x",
        chunk_id="chunk_1",
        vector=(0.1, 0.2),
        payload={"source_id": "src"},
    )

    assert backend.delete_point(spec_id="spec_x", chunk_id="chunk_1") is True
    assert backend.delete_point(spec_id="spec_x", chunk_id="chunk_1") is False


def test_search_points_honors_source_filter_and_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search should pass optional source filter and enforce limit."""
    monkeypatch.setattr(qdrant_backend_module, "QdrantClientSubstrate", _FakeSubstrate)

    backend = QdrantEmbeddingBackend(settings=_qdrant_settings())

    backend.upsert_point(
        spec_id="spec_search",
        chunk_id="chunk_1",
        vector=(0.1, 0.2),
        payload={"source_id": "src_a"},
    )
    backend.upsert_point(
        spec_id="spec_search",
        chunk_id="chunk_2",
        vector=(0.2, 0.3),
        payload={"source_id": "src_b"},
    )

    filtered = backend.search_points(
        spec_id="spec_search",
        source_id="src_a",
        query_vector=(0.1, 0.2),
        limit=10,
    )
    assert len(filtered) == 1
    assert filtered[0].payload["source_id"] == "src_a"

    limited = backend.search_points(
        spec_id="spec_search",
        source_id="",
        query_vector=(0.1, 0.2),
        limit=1,
    )
    assert len(limited) == 1
