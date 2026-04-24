"""Integration-style Embedding tests for service flow composition."""

from __future__ import annotations

from lib.shared.envelope import EnvelopeKind, new_meta
from services.state.embedding.config import EmbeddingServiceSettings
from services.state.embedding.implementation import (
    DefaultEmbeddingService,
)
from services.state.embedding.tests.test_service import (
    FakeQdrantIndex,
    FakeRepository,
)


def _meta():
    """Build deterministic envelope metadata."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def test_spec_source_chunk_embedding_flow_with_fakes() -> None:
    """Service should stitch repository and index writes across core embedding flow."""
    repo = FakeRepository()
    index = FakeQdrantIndex()
    service = DefaultEmbeddingService(
        settings=EmbeddingServiceSettings(max_list_limit=50),
        repository=repo,
        index_backend=index,
    )

    spec = service.upsert_spec(
        meta=_meta(),
        provider="ollama",
        name="mxbai-embed-large",
        version="1",
        dimensions=2,
    )
    assert spec.ok is True
    source = service.upsert_source(
        meta=_meta(),
        canonical_reference="vault://note",
        source_type="note",
        service="vault",
        principal="operator",
        metadata={},
    )
    assert source.ok is True

    chunk = service.upsert_chunk(
        meta=_meta(),
        source_id=source.payload.value.id,
        chunk_ordinal=0,
        reference_range="0:10",
        content_hash="h1",
        text="hello",
        metadata={},
    )
    assert chunk.ok is True

    embedded = service.upsert_embedding_vector(
        meta=_meta(),
        chunk_id=chunk.payload.value.id,
        spec_id=spec.payload.value.id,
        vector=[0.1, 0.2],
    )
    assert embedded.ok is True
