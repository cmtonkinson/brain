"""Real-provider integration tests for EAS Postgres repository."""

from __future__ import annotations

import hashlib

import pytest

from packages.brain_shared.config import load_settings
from services.state.embedding_authority.data.repository import (
    PostgresEmbeddingRepository,
)
from services.state.embedding_authority.data.runtime import EmbeddingPostgresRuntime
from services.state.embedding_authority.domain import EmbeddingStatus
from tests.integration.helpers import real_provider_tests_enabled


pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def test_spec_source_chunk_embedding_roundtrip() -> None:
    """Repository should persist spec/source/chunk/embedding state transitions."""
    runtime = EmbeddingPostgresRuntime.from_settings(load_settings())
    repo = PostgresEmbeddingRepository(runtime.schema_sessions)

    canonical = "ollama:mxbai-embed-large:1:2"
    spec = repo.upsert_spec(
        provider="ollama",
        name="mxbai-embed-large",
        version="1",
        dimensions=2,
        hash_bytes=hashlib.sha256(canonical.encode("utf-8")).digest(),
        canonical_string=canonical,
    )
    repo.set_active_spec(spec_id=spec.id)
    assert repo.get_active_spec_id() == spec.id

    source = repo.upsert_source(
        canonical_reference="vault://note",
        source_type="note",
        service="vault",
        principal="operator",
        metadata={},
    )
    chunk = repo.upsert_chunk(
        source_id=source.id,
        chunk_ordinal=0,
        reference_range="0:10",
        content_hash="h1",
        text="hello",
        metadata={},
    )
    embedding = repo.upsert_embedding(
        chunk_id=chunk.id,
        spec_id=spec.id,
        content_hash="h1",
        status=EmbeddingStatus.INDEXED,
        error_detail="",
    )

    assert embedding.status == EmbeddingStatus.INDEXED
